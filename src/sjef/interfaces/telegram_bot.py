"""Telegram-bot: de bedien-interface voor de supermarkt-agent.

Commando's:
  /plan                         -> weekmenu op de standaard macro-modus
  /plan cut|onderhoud|bulk      -> kies de macro-modus voor deze week
  /plan <vrije opdracht>        -> bv. "4x avondeten voor 4 personen, 2 lunches
                                   voor 2, 3 gezonde snacks"
  /status                       -> lopende bezorgingen
  /help

Autonome wekelijkse run (config.yaml -> weekly.auto.enabled): de bot maakt op een
vast tijdstip zelf een voorstel en stuurt het naar je voor goedkeuring. Er wordt
NOOIT automatisch besteld.

Veiligheid:
  * Alleen TELEGRAM_ALLOWED_USER_ID mag de bot bedienen.
  * Bestellen gebeurt in twee stappen: eerst een slot kiezen, dan een expliciete
    bevestig-knop. Pas dan wordt place_order aangeroepen.
  * place_order respecteert DRY_RUN en de uitgavenlimiet.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from sjef.config import Config, Secrets
from sjef.household.onboarding import OnboardingFlow
from sjef.household.profiles import Profiles
from sjef.interfaces import formatting
from sjef.picnic.picnic_client import PicnicClient
from sjef.planning import orchestrator

log = logging.getLogger(__name__)

# Conversatie-states voor /setup
ONB_ASK = 1


def _authorized(update: Update, secrets: Secrets) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    return (
        secrets.telegram_allowed_user_id is not None
        and uid == secrets.telegram_allowed_user_id
    )


def _effective_dry_run(app: Application) -> bool:
    """Actuele dry-run-stand: config.yaml (safety.dry_run, bv. via dashboard
    gewijzigd) overschrijft de .env-waarde. Vers ingelezen zodat een wijziging
    in het dashboard ook in de draaiende bot doorwerkt."""
    secrets: Secrets = app.bot_data["secrets"]
    return Config.load().dry_run(env_default=secrets.dry_run)


def _get_picnic(app: Application) -> PicnicClient:
    """Lazily één PicnicClient maken en hergebruiken (gedeeld door commands + jobs).
    Wordt opnieuw gemaakt als de dry-run-stand sinds de vorige keer wijzigde."""
    secrets: Secrets = app.bot_data["secrets"]
    dry = _effective_dry_run(app)
    client = app.bot_data.get("picnic")
    if client is None or client.dry_run != dry:
        client = PicnicClient(
            username=secrets.picnic_username,
            password=secrets.picnic_password,
            country_code=secrets.picnic_country_code,
            auth_token=secrets.picnic_auth_token,
            dry_run=dry,
        )
        app.bot_data["picnic"] = client
    return client


async def _send_proposal(
    bot: Bot, chat_id: int, proposal: dict, app: Application, prefix: str = ""
) -> None:
    """Stuur het voorstel + slotkeuze. Slaat de actieve sessie op in bot_data,
    zodat zowel /plan als de auto-run dezelfde goedkeuringsknoppen gebruiken."""
    if prefix:
        await bot.send_message(chat_id, prefix)
    # Voorstel over meerdere berichten zodat ALLE producten getoond worden.
    for msg in formatting.proposal_messages(proposal):
        await bot.send_message(
            chat_id,
            msg["text"],
            parse_mode=ParseMode.MARKDOWN if msg["markdown"] else None,
        )

    if not proposal["matched"]:
        await bot.send_message(chat_id, "Geen producten gevonden om te bestellen.")
        return

    slots = [s for s in proposal["slots"] if s.get("available", True)][:8]
    if not slots:
        await bot.send_message(
            chat_id,
            "⚠️ Geen bezorgslots gevonden. Probeer later opnieuw of kies een slot in de app.",
        )
        return

    buttons = [
        [InlineKeyboardButton(s["label"], callback_data=f"slot:{i}")]
        for i, s in enumerate(slots)
    ]
    buttons.append([InlineKeyboardButton("❌ Annuleren", callback_data="cancel")])
    app.bot_data["active"] = {"proposal": proposal, "slots": slots, "chosen_slot": None}
    await bot.send_message(
        chat_id, "🕒 Kies een bezorgslot:", reply_markup=InlineKeyboardMarkup(buttons)
    )


# ----------------------------------------------------------------- commands
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.application.bot_data["secrets"]
    if not _authorized(update, secrets):
        await update.message.reply_text("⛔ Niet geautoriseerd.")
        log.warning(
            "Ongeautoriseerde toegang door user-id %s", update.effective_user.id
        )
        return
    await update.message.reply_text(
        "🧑‍🍳 Hoi, ik ben *Sjef* — jouw AI-keukenmaatje.\n\n"
        "/plan — ik maak een weekmenu + boodschappen op jullie doelen\n"
        "/plan bulk — kies een macro-modus (cut/onderhoud/bulk)\n"
        "/plan 4x avondeten voor 4 personen, 2 lunches voor 2, 3 snacks — vrije opdracht\n"
        "/setup — stel de profielen in (ik vraag je gegevens)\n"
        "/profiles — bekijk de profielen + berekende dagdoelen\n"
        "/status — lopende bezorgingen\n\n"
        f"{'🧪 Proefmodus: ik zet alles klaar maar bestel niets.' if _effective_dry_run(context.application) else '🔴 Live: na jouw goedkeuring zet ik de boodschappen écht klaar.'}"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


# ------------------------------------------------------- profielen & onboarding
async def cmd_profiles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.application.bot_data["secrets"]
    if not _authorized(update, secrets):
        await update.message.reply_text("⛔ Niet geautoriseerd.")
        return
    profiles = Profiles.load()
    if not profiles:
        await update.message.reply_text(
            "Nog geen profielen ingesteld. Doe /setup om ze aan te maken."
        )
        return
    lines = [f"👥 Huishouden — {profiles.days} dagen per bestelling"]
    if profiles.household_notes:
        lines.append(f"Notitie: {profiles.household_notes}")
    lines.append("")
    for p in profiles.persons:
        lines.append(p.summary_line())
        lines.append("")
    await update.message.reply_text("\n".join(lines).strip())


def _onb_keyboard(flow: OnboardingFlow):
    """Maak knoppen voor keuze/ja-nee-velden, anders verwijder het toetsenbord."""
    f = flow.current_field()
    if f and f.kind in ("choice", "bool") and f.choices:
        rows = [[c] for c in f.choices]
        if f.optional:
            rows.append(["skip"])
        return ReplyKeyboardMarkup(rows, one_time_keyboard=True, resize_keyboard=True)
    if f and f.optional:
        return ReplyKeyboardMarkup(
            [["skip"]], one_time_keyboard=True, resize_keyboard=True
        )
    return ReplyKeyboardRemove()


async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    secrets: Secrets = context.application.bot_data["secrets"]
    if not _authorized(update, secrets):
        await update.message.reply_text("⛔ Niet geautoriseerd.")
        return ConversationHandler.END
    flow = OnboardingFlow()
    context.user_data["onb"] = flow
    await update.message.reply_text(
        "🛠️ Profielen instellen. Typ /cancel om te stoppen.\n"
        "Op het eind wordt alles opgeslagen in profiles.yaml (lokaal, privé)."
    )
    await update.message.reply_text(
        flow.current_question(), reply_markup=_onb_keyboard(flow)
    )
    return ONB_ASK


async def setup_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    flow: OnboardingFlow = context.user_data.get("onb")
    if not flow:
        await update.message.reply_text("Geen actieve setup. Doe /setup.")
        return ConversationHandler.END

    ok, err = flow.submit(update.message.text or "")
    if not ok:
        await update.message.reply_text(f"⚠️ {err}", reply_markup=_onb_keyboard(flow))
        return ONB_ASK

    if flow.done:
        try:
            Profiles.save(flow.to_profiles_dict())
        except Exception as exc:
            log.exception("profiel opslaan mislukt")
            await update.message.reply_text(
                f"❌ Opslaan mislukt: {exc}", reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
        context.user_data.pop("onb", None)
        await update.message.reply_text(
            f"✅ Profielen opgeslagen ({len(flow.persons)} perso(o)n(en)).\n"
            "Bekijk ze met /profiles, of maak een boodschappenplan met /plan.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    await update.message.reply_text(
        flow.current_question(), reply_markup=_onb_keyboard(flow)
    )
    return ONB_ASK


async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("onb", None)
    await update.message.reply_text(
        "Setup afgebroken. Er is niets gewijzigd.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.application.bot_data["secrets"]
    if not _authorized(update, secrets):
        await update.message.reply_text("⛔ Niet geautoriseerd.")
        return
    try:
        picnic = _get_picnic(context.application)
        deliveries = await asyncio.to_thread(picnic.api.get_current_deliveries)
        if not deliveries:
            await update.message.reply_text("Geen lopende bezorgingen.")
            return
        await update.message.reply_text(f"📦 {len(deliveries)} lopende bezorging(en).")
    except Exception as exc:
        log.exception("status-fout")
        await update.message.reply_text(f"Fout bij ophalen status: {exc}")


def _parse_plan_args(config: Config, args: list[str]) -> tuple[str | None, str | None]:
    """Bepaal (mode, request) uit de /plan-argumenten.

    - geen args            -> (None, None)        gebruikt default mode
    - exact een modusnaam  -> (mode, None)
    - alles anders         -> (None, vrije tekst) vrije opdracht
    """
    if not args:
        return None, None
    joined = " ".join(args).strip()
    if joined.lower() in config.macro_modes:
        return joined.lower(), None
    return None, joined


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.application.bot_data["secrets"]
    config: Config = context.application.bot_data["config"]
    if not _authorized(update, secrets):
        await update.message.reply_text("⛔ Niet geautoriseerd.")
        return

    mode, request = _parse_plan_args(config, context.args)
    note = (
        f" (verzoek: {request})" if request else (f" (modus: {mode})" if mode else "")
    )
    await update.message.reply_text(f"🧠 Weekmenu genereren en producten zoeken…{note}")

    try:
        picnic = _get_picnic(context.application)
        proposal = await asyncio.to_thread(
            orchestrator.build_proposal, config, secrets, picnic, mode, request
        )
    except Exception as exc:
        log.exception("plan-fout")
        await update.message.reply_text(f"❌ Kon geen voorstel maken: {exc}")
        return

    await _send_proposal(
        context.bot, update.effective_chat.id, proposal, context.application
    )


# ------------------------------------------------------- autonome wekelijkse run
async def weekly_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Draait dagelijks op het ingestelde tijdstip, maar doet alleen iets op de
    gekozen weekdag. Maakt een voorstel en stuurt het voor goedkeuring."""
    config: Config = context.application.bot_data["config"]
    secrets: Secrets = context.application.bot_data["secrets"]

    if dt.datetime.now().weekday() != config.auto_weekday:
        return

    chat_id = secrets.telegram_allowed_user_id
    log.info("Autonome wekelijkse run gestart")
    try:
        picnic = _get_picnic(context.application)
        proposal = await asyncio.to_thread(
            orchestrator.build_proposal,
            config,
            secrets,
            picnic,
            config.auto_mode,
            config.auto_request,
        )
    except Exception as exc:
        log.exception("auto-run fout")
        await context.bot.send_message(chat_id, f"❌ Wekelijkse run mislukt: {exc}")
        return

    await _send_proposal(
        context.bot,
        chat_id,
        proposal,
        context.application,
        prefix="🗓️ Wekelijkse boodschappen — voorstel staat klaar, keur goed of annuleer:",
    )


# ---------------------------------------------------------------- callbacks
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    secrets: Secrets = context.application.bot_data["secrets"]
    config: Config = context.application.bot_data["config"]
    query = update.callback_query
    await query.answer()

    if not _authorized(update, secrets):
        await query.edit_message_text("⛔ Niet geautoriseerd.")
        return

    data = query.data or ""
    active = context.application.bot_data.get("active") or {}

    if data == "cancel":
        context.application.bot_data["active"] = {}
        await query.edit_message_text("❌ Geannuleerd. Er is niets besteld.")
        return

    if data.startswith("slot:"):
        idx = int(data.split(":", 1)[1])
        slots = active.get("slots", [])
        if idx >= len(slots):
            await query.edit_message_text(
                "Slot niet meer beschikbaar. Doe /plan opnieuw."
            )
            return
        slot = slots[idx]
        active["chosen_slot"] = slot
        total = formatting.euro(active.get("proposal", {}).get("total_cents", 0))
        eff_dry = _effective_dry_run(context.application)
        live = "" if eff_dry else " (LIVE — er wordt echt besteld!)"
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"✅ Bevestig & bestel {total}{live}", callback_data="confirm"
                    )
                ],
                [InlineKeyboardButton("❌ Annuleren", callback_data="cancel")],
            ]
        )
        await query.edit_message_text(
            f"Bezorgslot: {slot['label']}\nTotaal: {total}\n\n"
            f"{'🧪 DRY-RUN: bevestigen simuleert alleen.' if eff_dry else '🔴 Dit plaatst een echte bestelling.'}",
            reply_markup=kb,
        )
        return

    if data == "confirm":
        proposal = active.get("proposal")
        slot = active.get("chosen_slot")
        if not proposal or not slot:
            await query.edit_message_text("Geen actief voorstel. Doe /plan opnieuw.")
            return
        await query.edit_message_text("⏳ Bezig met bestellen…")
        try:
            picnic = _get_picnic(context.application)
            result = await asyncio.to_thread(
                orchestrator.place_order, config, picnic, proposal, slot["slot_id"]
            )
        except Exception as exc:
            log.exception("bestel-fout")
            await query.edit_message_text(f"❌ Bestellen mislukt: {exc}")
            return

        if not result["ok"]:
            await query.edit_message_text(f"🚫 {result['reason']}")
            return

        if result["dry_run"]:
            msg = (
                "🧪 DRY-RUN voltooid — er is NIETS echt besteld.\n"
                f"Zou besteld hebben: {formatting.euro(result['total_cents'])} "
                f"voor slot {slot['label']}.\n\n"
                "Zet DRY_RUN=false in .env om echt te bestellen."
            )
        elif result.get("needs_app_confirm"):
            msg = (
                "✅ Mandje gevuld en slot geboekt, maar geen order-id ontvangen.\n"
                "👉 Open de Picnic-app en tik op 'Bevestigen' om af te ronden."
            )
        else:
            msg = (
                f"✅ Besteld! {formatting.euro(result['total_cents'])}\n"
                f"Bezorgslot: {slot['label']}\nOrder: {result.get('order_id', '?')}"
            )
        context.application.bot_data["active"] = {}
        await query.edit_message_text(msg)


def build_application(config: Config, secrets: Secrets) -> Application:
    if not secrets.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ontbreekt in .env")
    if secrets.telegram_allowed_user_id is None:
        raise RuntimeError(
            "TELEGRAM_ALLOWED_USER_ID ontbreekt in .env (veiligheidsslot)"
        )

    app = Application.builder().token(secrets.telegram_bot_token).build()
    app.bot_data["config"] = config
    app.bot_data["secrets"] = secrets
    app.bot_data["active"] = {}

    # Onboarding-conversatie (/setup). Eerst registreren zodat /cancel werkt.
    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={
            ONB_ASK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, setup_answer),
            ],
        },
        fallbacks=[CommandHandler("cancel", setup_cancel)],
        name="onboarding",
    )
    app.add_handler(setup_conv)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("profiles", cmd_profiles))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(on_callback))

    if config.auto_enabled:
        if app.job_queue is None:
            log.warning(
                "weekly.auto staat aan maar job-queue ontbreekt. "
                "Installeer: pip install 'python-telegram-bot[job-queue]'"
            )
        else:
            hour, minute = config.auto_time
            local_tz = dt.datetime.now().astimezone().tzinfo
            app.job_queue.run_daily(
                weekly_job, time=dt.time(hour=hour, minute=minute, tzinfo=local_tz)
            )
            log.info(
                "Autonome run gepland: elke %s om %02d:%02d (lokale tijd)",
                config.auto_weekday,
                hour,
                minute,
            )
    return app
