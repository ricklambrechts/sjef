"""Web-dashboard voor de supermarkt-agent (Streamlit).

Starten:
    uv run sjef dashboard

Twee tabs:
  • Plan        — genereer weekplan, bewerk boodschappen, kies slot, bestel.
  • Instellingen — personen, calorie-/macrodoelen, huishouden en budget aanpassen
                   en opslaan (schrijft profiles.yaml en config.yaml).

Hergebruikt dezelfde backend als de Telegram-bot. Respecteert DRY_RUN uit .env.
"""

from __future__ import annotations

import datetime as _dt
import math

import pandas as pd
import streamlit as st

from sjef.config import Config, Secrets
from sjef.household import nutrition
from sjef.household.profiles import Profiles
from sjef.picnic.picnic_client import PicnicClient
from sjef.planning import orchestrator

st.set_page_config(
    page_title="Sjef — jouw AI-keukenmaatje", page_icon="🧑‍🍳", layout="wide"
)

# ---- Sjef look & feel ----------------------------------------------------
CUSTOM_CSS = """
<style>
/* warme achtergrond + ademruimte */
.stApp { background: linear-gradient(180deg, #FBF7F0 0%, #F3F0E7 100%); }
.block-container { padding-top: 2.2rem; max-width: 1150px; }

/* Hero-kop */
.sjef-hero {
    background: linear-gradient(120deg, #2E7D4F 0%, #3E9E63 55%, #D9A441 140%);
    border-radius: 20px; padding: 24px 28px; color: #fff;
    box-shadow: 0 10px 30px rgba(46,125,79,0.25); margin-bottom: 8px;
}
.sjef-hero h1 { color:#fff; font-size: 2.1rem; margin: 0; font-weight: 800; letter-spacing:-.5px; }
.sjef-hero p  { color: #EAF6EE; margin: 6px 0 0; font-size: 1.02rem; }

/* knoppen ronder + steviger */
.stButton > button {
    border-radius: 12px; font-weight: 600; border: none;
    transition: transform .05s ease, box-shadow .15s ease;
}
.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(0,0,0,.12); }

/* metric-kaartjes */
[data-testid="stMetric"] {
    background: #fff; border: 1px solid #ECE6DA; border-radius: 14px;
    padding: 12px 16px; box-shadow: 0 2px 8px rgba(0,0,0,.04);
}
/* tabs wat groter */
.stTabs [data-baseweb="tab"] { font-size: 1.02rem; font-weight: 600; }
/* expanders als kaarten */
[data-testid="stExpander"] { border-radius: 14px; border: 1px solid #ECE6DA; background:#fff; }
</style>
"""

# Wisselende, vrolijke openingszinnen van Sjef (deterministisch per dag gekozen,
# zonder Math.random/Date — gewoon op weekdag-index zodat het stabiel is).
SJEF_QUIPS = [
    "Wat gaan we deze week lekkers in huis halen? 🍳",
    "Honger? Ik regel het mandje, jij geniet. 🥗",
    "Klaar om slim te shoppen — gezond én voordelig. 💪",
    "Even denken aan je macro's… komt goed. 📊",
    "Vers plan, vol eiwit, weinig gedoe. 🫑",
    "Jouw week, jouw doelen — ik doe de boodschappen. 🛒",
    "Laten we koken zonder na te denken over de lijst. 👨‍🍳",
]

SEXES = ["man", "vrouw"]
GOALS = ["cut", "onderhoud", "bulk"]
ACTIVITIES = list(nutrition.ACTIVITY_FACTORS.keys())
DIETS = ["omnivoor", "vegetarisch", "pescotarisch", "veganistisch"]


@st.cache_resource(show_spinner=False)
def get_picnic(dry_run: bool) -> PicnicClient:
    s = Secrets.load()
    return PicnicClient(
        username=s.picnic_username,
        password=s.picnic_password,
        country_code=s.picnic_country_code,
        auth_token=s.picnic_auth_token,
        dry_run=dry_run,
    )


def eur(cents: int) -> str:
    return f"€{cents / 100:.2f}"


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _text(v) -> str:
    """Normaliseer lege tekstcellen, ook pandas 3's NaN voor stringkolommen."""
    return "" if pd.isna(v) else str(v)


def _lst(v) -> list[str]:
    return [x.strip() for x in _text(v).split(",") if x.strip()]


config = Config.load()
secrets = Secrets.load()
# Effectieve dry-run: config.yaml (safety.dry_run) overschrijft, anders .env.
dry = config.dry_run(env_default=secrets.dry_run)

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Hero-header met persoonlijkheid. Quip stabiel per weekdag (geen random nodig).
_quip = SJEF_QUIPS[_dt.date.today().weekday() % len(SJEF_QUIPS)]
st.markdown(
    f"""
    <div class="sjef-hero">
        <h1>🧑‍🍳 Sjef</h1>
        <p>{_quip}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if dry:
    st.info(
        "🧪 Proefmodus — Sjef zet alles klaar maar bestelt niets. Aanzetten kan bij ‘Instellingen’."
    )
else:
    st.error(
        "🔴 Live — een goedkeuring zet de boodschappen écht klaar bij Picnic. Terug naar proef via ‘Instellingen’."
    )

# Sidebar: live doel-overzicht
with st.sidebar:
    st.markdown("### 🧑‍🍳 Aan tafel")
    _profiles = Profiles.load()
    if _profiles:
        for p in _profiles.persons:
            t = p.targets
            st.metric(
                f"{p.name} · {p.goal}",
                f"{t['kcal']} kcal",
                f"{t['eiwit_g']}g eiwit · {t['koolhydraten_g']}g kh",
                delta_color="off",
            )
        st.caption(f"🗓️ {_profiles.days} dagen per bestelling")
    else:
        st.warning("Nog niemand aan tafel. Voeg mensen toe bij ‘Instellingen’.")
    st.divider()
    st.caption(
        f"💶 Budget €{config.max_order_eur:.0f} · streef €{config.budget_target_eur or 0:.0f}"
    )
    st.caption(f"🧠 Sjef denkt met: {secrets.planner_model}")

tab_plan, tab_settings = st.tabs(["🍽️ Deze week", "⚙️ Instellingen"])

# ============================================================ PLAN
with tab_plan:
    st.subheader("Wat eten we deze week?")
    c1, c2 = st.columns(2)
    with c1:
        request = st.text_input(
            "Zin in iets specifieks? (optioneel)",
            placeholder="bv. 2x vis i.p.v. kip, of meer Aziatisch",
        )
    with c2:
        extras_raw = st.text_area(
            "Nog iets meenemen? — één per regel (optioneel)",
            placeholder="wc-papier\nafwasmiddel\ntandpasta",
            height=90,
        )

    if st.button("🍳 Sjef, maak een plan", type="primary"):
        extra_items = [ln.strip() for ln in extras_raw.splitlines() if ln.strip()]
        try:
            with st.spinner(
                "Sjef stelt het menu samen en zoekt de boodschappen bij Picnic… (15-40s)"
            ):
                proposal = orchestrator.build_proposal(
                    config,
                    secrets,
                    get_picnic(dry),
                    mode=None,
                    request=request or None,
                    extra_items=extra_items,
                )
            st.session_state["proposal"] = proposal
            st.session_state.pop("order_result", None)
        except Exception as exc:
            st.exception(exc)

    proposal = st.session_state.get("proposal")
    if not proposal:
        st.info(
            "👋 Nog geen plan. Druk op **‘Sjef, maak een plan’** en ik regel je week."
        )
    else:
        persons = proposal.get("persons") or []
        if persons:
            cols = st.columns(len(persons))
            for col, p in zip(cols, persons, strict=True):
                t = p["targets"]
                col.metric(
                    f"{p['name']} ({p['goal']})",
                    f"{t['kcal']} kcal",
                    f"{t['eiwit_g']}g eiwit",
                    delta_color="off",
                )
        if proposal["plan"].get("samenvatting"):
            st.caption(proposal["plan"]["samenvatting"])

        person_names = [p["name"] for p in persons]

        st.subheader("📋 Menu")
        st.caption(
            "Macro's per ingrediënt/persoon zijn berekend uit de echte Picnic-"
            "voedingswaarden. Let op: verse producten zonder voedingstabel (‘—’, bv. "
            "groente/fruit) tellen NIET mee — **eiwit is accuraat, kcal is een ondergrens**."
        )
        for day in proposal["plan"].get("dagen", []):
            # Per-persoon dagtotalen in de koptekst (echte berekende waarden).
            day_pp = day.get("per_persoon") or {}
            head = f"{day.get('dag', '?')}"
            if day_pp:
                head += " — " + " · ".join(
                    f"{name}: {day_pp[name]['kcal']} kcal / {day_pp[name]['eiwit_g']}g eiwit"
                    for name in person_names
                    if name in day_pp
                )
            else:
                head += f" — {day.get('totaal_kcal', '?')} kcal / {day.get('totaal_eiwit_g', '?')}g eiwit"
            with st.expander(head):
                for m in day.get("maaltijden", []):
                    st.markdown(
                        f"**{str(m.get('type', '')).capitalize()}** — {m.get('naam', '')}"
                    )
                    # Per-persoon maaltijdtotalen.
                    mpp = m.get("per_persoon") or {}
                    if mpp:
                        st.caption(
                            "  ·  ".join(
                                f"**{name}**: {mpp[name]['kcal']} kcal / {mpp[name]['eiwit_g']}g eiwit"
                                for name in person_names
                                if name in mpp
                            )
                        )
                    ings = m.get("ingredienten") or []
                    if ings:
                        rows = []
                        for i in ings:
                            row = {
                                "Ingrediënt": i.get("naam", ""),
                                "Gram (tot.)": i.get("gram", ""),
                            }
                            pp = i.get("per_persoon") or {}
                            for name in person_names:
                                cell = pp.get(name)
                                row[name] = (
                                    f"{cell['gram']}g · {cell['kcal']}kcal · {cell['eiwit_g']}g eiwit"
                                    if cell
                                    else "—"
                                )
                            row["Picnic-product"] = i.get("bron_product") or "—"
                            rows.append(row)
                        st.dataframe(
                            pd.DataFrame(rows),
                            hide_index=True,
                            use_container_width=True,
                        )

        # Voorraadkast-items (kruiden/sauzen/olie): vraag of je ze al in huis hebt.
        pantry = [m for m in proposal["matched"] if m.get("voorraadkast")]
        skip_ids = set()
        if pantry:
            st.subheader("🧂 Heb je deze al in huis?")
            st.caption(
                "Lang houdbare basics (kruiden, sauzen, olie). Vink aan wat je al "
                "hebt — die laten we uit de bestelling en besparen geld."
            )
            for m in pantry:
                have = st.checkbox(
                    f"{m['name']} ({m.get('unit_quantity', '')}) — {eur(m['unit_price_cents'])}",
                    value=False,
                    key=f"pantry_{m['id']}",
                )
                if have:
                    skip_ids.add(m["id"])

        shop_items = [m for m in proposal["matched"] if m["id"] not in skip_ids]

        st.subheader("🛒 Boodschappen")
        st.caption("Pas aantallen aan of verwijder regels. Het totaal werkt live mee.")
        base = pd.DataFrame(
            [
                {
                    "Product": m["name"],
                    "Hoeveelheid": m.get("unit_quantity", ""),
                    "Aantal": m["count"],
                    "Stukprijs": m["unit_price_cents"] / 100,
                    "_id": m["id"],
                }
                for m in shop_items
            ]
        )
        edited = st.data_editor(
            base,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "Product": st.column_config.TextColumn(disabled=True),
                "Hoeveelheid": st.column_config.TextColumn(disabled=True),
                "Aantal": st.column_config.NumberColumn(min_value=0, step=1),
                "Stukprijs": st.column_config.NumberColumn(
                    format="€%.2f", disabled=True
                ),
                "_id": None,
            },
            key="shop_editor",
        )

        by_id = {m["id"]: m for m in shop_items}
        current_matched = []
        for _, row in edited.iterrows():
            orig = by_id.get(row.get("_id"))
            if orig is None:
                continue
            try:
                cnt = int(row["Aantal"])
            except (ValueError, TypeError):
                cnt = orig["count"]
            if cnt < 1:
                continue
            nm = dict(orig)
            nm["count"] = cnt
            nm["line_total_cents"] = orig["unit_price_cents"] * cnt
            current_matched.append(nm)
        total_cents = sum(m["line_total_cents"] for m in current_matched)

        if proposal.get("unmatched"):
            st.warning(
                "Niet gevonden (handmatig in de Picnic-app): "
                + ", ".join(u["item"] for u in proposal["unmatched"])
            )

        m1, m2 = st.columns(2)
        m1.metric("Totaal", eur(total_cents))
        m2.metric("Producten", len(current_matched))
        if total_cents > config.max_order_eur * 100:
            st.warning(
                f"Boven de budgetlimiet van €{config.max_order_eur:.0f} — bestellen wordt geweigerd."
            )

        st.subheader("🚚 Bezorgen & bestellen")
        slots = [s for s in proposal.get("slots", []) if s.get("available", True)]
        if not slots:
            st.warning("Geen bezorgslots beschikbaar. Probeer later opnieuw.")
        else:
            labels = [s["label"] for s in slots]
            chosen = st.selectbox("Bezorgslot", labels)
            btn = "✅ Goedkeuren — Sjef zet 't klaar" + (
                " (proef)" if dry else "  —  LIVE!"
            )
            if st.button(btn, type="primary"):
                slot = slots[labels.index(chosen)]
                order_proposal = dict(proposal)
                order_proposal["matched"] = current_matched
                order_proposal["total_cents"] = total_cents
                try:
                    with st.spinner("Sjef vult het mandje en boekt het slot…"):
                        result = orchestrator.place_order(
                            config, get_picnic(dry), order_proposal, slot["slot_id"]
                        )
                    st.session_state["order_result"] = {
                        "result": result,
                        "slot": slot["label"],
                    }
                except Exception as exc:
                    st.exception(exc)

        res = st.session_state.get("order_result")
        if res:
            r = res["result"]
            if not r["ok"]:
                st.error(f"🚫 {r['reason']}")
            elif r["dry_run"]:
                st.success(
                    f"🧪 DRY-RUN voltooid — niets echt besteld. Zou {eur(r['total_cents'])} besteld hebben voor {res['slot']}."
                )
            elif r.get("needs_app_confirm"):
                st.warning(
                    f"🛒 **Mandje klaargezet** ({eur(r['total_cents'])}, slot {res['slot']}) — "
                    "maar er is nog **NIET besteld of betaald**.\n\n"
                    "Open de Picnic-app en reken daar af om de bestelling te plaatsen. "
                    "_(Picnic vereist de laatste bevestiging/betaling in de app zelf.)_"
                )
            else:
                st.success(
                    f"✅ Besteld! {eur(r['total_cents'])} voor {res['slot']} (order {r.get('order_id', '?')})."
                )

# ============================================================ INSTELLINGEN
with tab_settings:
    st.subheader("👥 Personen & doelen")
    st.caption(
        "Vul gegevens in; calorie- en macrodoelen worden automatisch berekend. "
        "‘Kcal handmatig’ overschrijft het berekende caloriedoel (leeg = automatisch)."
    )
    prof = Profiles.load()
    raw_persons = prof.raw.get("persons", []) if prof else []
    pdf = pd.DataFrame(
        [
            {
                "Actief": bool(p.get("actief", True)),
                "Naam": p.get("name", ""),
                "Geslacht": p.get("sex", "man"),
                "Leeftijd": p.get("age", 30),
                "Lengte (cm)": p.get("height_cm", 175),
                "Gewicht (kg)": p.get("weight_kg", 75),
                "Vet %": p.get("bodyfat_pct"),
                "Doel": p.get("goal", "onderhoud"),
                "Activiteit": p.get("activity", "matig"),
                "Kcal handmatig": p.get("kcal_override"),
                "Dieet": p.get("diet_profile", "omnivoor"),
                "Uitsluiten": ", ".join(p.get("exclude") or []),
                "Voorkeuren": ", ".join(p.get("prefer") or []),
                "Training": p.get("training", ""),
                "Notities": p.get("notes", ""),
            }
            for p in raw_persons
        ]
    )
    if pdf.empty:
        pdf = pd.DataFrame(
            [
                {
                    "Actief": True,
                    "Naam": "",
                    "Geslacht": "man",
                    "Leeftijd": 30,
                    "Lengte (cm)": 180,
                    "Gewicht (kg)": 80,
                    "Vet %": None,
                    "Doel": "onderhoud",
                    "Activiteit": "matig",
                    "Kcal handmatig": None,
                    "Dieet": "omnivoor",
                    "Uitsluiten": "",
                    "Voorkeuren": "",
                    "Training": "",
                    "Notities": "",
                }
            ]
        )

    edited_p = st.data_editor(
        pdf,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        column_config={
            "Actief": st.column_config.CheckboxColumn(
                help="Uit = telt niet mee in plan, macro's en boodschappen"
            ),
            "Geslacht": st.column_config.SelectboxColumn(options=SEXES, required=True),
            "Leeftijd": st.column_config.NumberColumn(
                min_value=1, max_value=120, step=1
            ),
            "Lengte (cm)": st.column_config.NumberColumn(
                min_value=100.0, max_value=230.0
            ),
            "Gewicht (kg)": st.column_config.NumberColumn(
                min_value=30.0, max_value=250.0
            ),
            "Vet %": st.column_config.NumberColumn(
                min_value=0.0, max_value=60.0, help="Optioneel"
            ),
            "Doel": st.column_config.SelectboxColumn(options=GOALS, required=True),
            "Activiteit": st.column_config.SelectboxColumn(
                options=ACTIVITIES, required=True
            ),
            "Kcal handmatig": st.column_config.NumberColumn(
                min_value=0, step=50, help="Leeg = automatisch berekenen"
            ),
            "Dieet": st.column_config.SelectboxColumn(options=DIETS, required=True),
        },
        key="persons_editor",
    )

    st.subheader("🏠 Huishouden")
    hh = prof.raw.get("household", {}) if prof else {}
    hc1, hc2 = st.columns(2)
    days = hc1.number_input("Dagen per bestelling", 1, 31, int(hh.get("days", 7)))
    shared = hc2.checkbox(
        "Dezelfde gerechten, andere porties", value=bool(hh.get("shared_meals", True))
    )
    hh_notes = st.text_area(
        "Huishoud-notities voor de planner (bv. insulineresistentie, voorkeuren)",
        value=hh.get("notes", "") or "",
        height=80,
    )

    st.subheader("🔒 Veiligheid — bestelmodus")
    if dry:
        st.write("Status: 🧪 **DRY-RUN** — bestellingen worden alleen gesimuleerd.")
        st.caption(
            "Zet dit uit om ECHT te kunnen bestellen. Dan kost een goedgekeurde "
            "bestelling echt geld via je Picnic-incasso."
        )
        confirm_live = st.checkbox(
            "Ik begrijp dat LIVE echte bestellingen plaatst die geld kosten"
        )
        if st.button("🔴 Schakel naar LIVE bestellen", disabled=not confirm_live):
            cfg = Config.load()
            cfg.set_dry_run(False)
            cfg.save()
            st.rerun()
    else:
        st.write("Status: 🔴 **LIVE** — een goedgekeurde bestelling kost echt geld.")
        if st.button("🧪 Terug naar veilige DRY-RUN", type="primary"):
            cfg = Config.load()
            cfg.set_dry_run(True)
            cfg.save()
            st.rerun()

    st.subheader("💶 Budget")
    bc1, bc2, bc3 = st.columns(3)
    max_order = bc1.number_input(
        "Harde limiet (€)", 10.0, 1000.0, float(config.max_order_eur), step=10.0
    )
    target = bc2.number_input(
        "Streefbudget (€)",
        10.0,
        1000.0,
        float(config.budget_target_eur or config.max_order_eur),
        step=10.0,
    )
    cost_conscious = bc3.checkbox(
        "Kostenbewust",
        value=config.cost_conscious,
        help="Eiwit ook uit goedkope bronnen (kwark, eieren, peulvruchten)",
    )

    if st.button("💾 Instellingen opslaan", type="primary"):
        new_persons = []
        for _, r in edited_p.iterrows():
            name = _text(r.get("Naam", "")).strip()
            if not name:
                continue
            person = {
                "name": name,
                "actief": bool(r.get("Actief", True)),
                "sex": r["Geslacht"],
                "age": int(_num(r["Leeftijd"]) or 30),
                "height_cm": float(_num(r["Lengte (cm)"]) or 175),
                "weight_kg": float(_num(r["Gewicht (kg)"]) or 75),
                "goal": r["Doel"],
                "activity": r["Activiteit"],
                "diet_profile": r["Dieet"],
                "exclude": _lst(r["Uitsluiten"]),
                "prefer": _lst(r["Voorkeuren"]),
                "training": _text(r["Training"]),
                "notes": _text(r["Notities"]),
            }
            bf = _num(r["Vet %"])
            if bf is not None:
                person["bodyfat_pct"] = float(bf)
            ko = _num(r["Kcal handmatig"])
            if ko is not None and float(ko) > 0:
                person["kcal_override"] = int(ko)
            new_persons.append(person)

        if not new_persons:
            st.error("Vul minstens één persoon met een naam in.")
        else:
            Profiles.save(
                {
                    "household": {
                        "days": int(days),
                        "shared_meals": bool(shared),
                        "notes": hh_notes,
                    },
                    "persons": new_persons,
                }
            )
            cfg = Config.load()
            cfg.raw.setdefault("limits", {})["max_order_eur"] = float(max_order)
            cfg.raw.setdefault("budget", {})["target_eur"] = float(target)
            cfg.raw["budget"]["cost_conscious"] = bool(cost_conscious)
            cfg.save()
            st.success(
                "✅ Opgeslagen! De volgende ‘Genereer plan’ gebruikt de nieuwe instellingen."
            )
            st.rerun()

    # Live preview van de berekende doelen
    prof2 = Profiles.load()
    if prof2:
        st.divider()
        st.caption(
            "Berekende dagdoelen met de huidige (opgeslagen) instellingen "
            "— inactieve personen tellen niet mee in plan/boodschappen:"
        )
        for p in prof2.all_persons:
            t = p.targets
            tag = "" if p.active else "  ⏸️ _inactief_"
            st.write(
                f"**{p.name}** ({p.goal}): {t['kcal']} kcal · {t['eiwit_g']}g eiwit · "
                f"{t['vet_g']}g vet · {t['koolhydraten_g']}g koolhydraten  _(TDEE ~{t['tdee']})_{tag}"
            )
