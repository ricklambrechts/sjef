"""Entrypoint voor de supermarkt-agent.

    python run.py bot              # start de Telegram-bot
    python run.py plan [modus]     # bouw een voorstel in de terminal (geen bestelling)
    python run.py selftest         # offline tests van de pure logica (geen credentials nodig)
"""
from __future__ import annotations

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("run")


def run_bot() -> None:
    from pathlib import Path
    from src.config import Config, Secrets
    from src.telegram_bot import build_application

    # state/ moet bestaan voor token-persistentie en (via launchd) logbestanden.
    (Path(__file__).parent / "state").mkdir(exist_ok=True)

    config = Config.load()
    secrets = Secrets.load()
    app = build_application(config, secrets)
    log.info("Bot start (dry_run=%s)…", secrets.dry_run)
    app.run_polling()


def run_plan(mode: str | None) -> None:
    from src.config import Config, Secrets
    from src.picnic_client import PicnicClient
    from src import orchestrator, formatting

    config = Config.load()
    secrets = Secrets.load()
    picnic = PicnicClient(
        username=secrets.picnic_username,
        password=secrets.picnic_password,
        country_code=secrets.picnic_country_code,
        auth_token=secrets.picnic_auth_token,
        dry_run=secrets.dry_run,
    )
    proposal = orchestrator.build_proposal(config, secrets, picnic, mode)
    print("\n" + formatting.format_proposal(proposal))
    print("\n(Alleen voorstel — er is niets besteld. Gebruik de bot om te bestellen.)")


def run_selftest() -> int:
    """Test de pure, netwerkloze logica. Geen API-keys of credentials nodig."""
    from src.config import Config
    from src import matcher, planner, formatting, orchestrator

    failures = 0

    def check(name, cond):
        nonlocal failures
        print(f"  {'✅' if cond else '❌'} {name}")
        if not cond:
            failures += 1

    print("config.yaml laden + macro-modes:")
    cfg = Config.load()
    check("default mode bestaat", cfg.default_mode in cfg.macro_modes)
    macros = cfg.macros_for("bulk")
    check("bulk heeft kcal+eiwit", "kcal_per_day" in macros and "protein_per_day" in macros)

    print("matcher.pick_best:")
    results = [
        {"id": "a1", "name": "Kipfilet naturel", "display_price": 499, "unit_quantity": "500 g"},
        {"id": "a2", "name": "Kip cordon bleu", "price": 399},
        {"id": "a3", "name": "Kipfilet bio", "display_price": 9999},  # te duur -> skip
        {"id": "a4", "name": "Iets anders", "price": 100},
    ]
    best = matcher.pick_best(results, "kipfilet", max_item_cents=2500)
    check("kiest naam-overlap (kipfilet)", best is not None and best["id"] == "a1")
    check("slaat te dure match over", all(c is None or c["id"] != "a3" for c in [best]))

    print("matcher.flatten_results (geneste Picnic-structuur):")
    nested = [{"items": [
        {"id": "n1", "name": "Kipfilet naturel", "display_price": 379, "unit_quantity": "200 g"},
        {"id": "n2", "name": "Kipfilet bio", "display_price": 969, "unit_quantity": "320 g"},
    ]}]
    flat = matcher.flatten_results(nested)
    check("nested -> 2 producten platgeslagen", len(flat) == 2)
    nbest = matcher.pick_best(nested, "kipfilet", max_item_cents=2500)
    check("pick_best werkt op geneste respons", nbest is not None and nbest["id"] == "n1")
    check("platte lijst blijft werken", len(matcher.flatten_results(results)) == len(results))

    print("matcher.shortlist (behoudt Picnic-volgorde, filtert op prijs):")
    sl_results = [{"items": [
        {"id": "eerste", "name": "Gele uien", "display_price": 99, "unit_quantity": "1 kg"},
        {"id": "tweede", "name": "Ui-chips", "display_price": 199, "unit_quantity": "150 gram"},
        {"id": "duur", "name": "Cadeaupakket ui", "display_price": 9999, "unit_quantity": "1 stuk"},
    ]}]
    sl = matcher.shortlist(sl_results, "ui", max_item_cents=2500)
    check("respecteert Picnic-volgorde (Gele uien eerst)", sl[0]["id"] == "eerste")
    check("filtert te dure match eruit", all(c["id"] != "duur" for c in sl))

    print("matcher.assemble_from_choices + fallback:")
    kip_cands = [
        {"id": "big", "name": "Kipfilet 800g", "unit_quantity": "800 gram", "price_cents": 800},
        {"id": "mini", "name": "Kipfilet 200g", "unit_quantity": "200 gram", "price_cents": 379},
    ]
    items_wc = [{
        "planned_item": "Kipfilet", "zoekterm": "kipfilet", "hoeveelheid": "1.4 kg",
        "geschat_aantal": 2, "voorraadkast": False, "candidates": kip_cands,
    }]
    asm = matcher.assemble_from_choices(items_wc, [{"index": 0, "product_id": "mini", "aantal": 3}])
    check("kiest het door Claude gekozen product", asm["matched"][0]["id"] == "mini")
    check("neemt aantal over", asm["matched"][0]["count"] == 3)
    check("voorraadkast-vlag doorgegeven (false)", asm["matched"][0]["voorraadkast"] is False)
    pantry_wc = [{
        "planned_item": "Sojasaus", "zoekterm": "sojasaus", "hoeveelheid": "1 fles",
        "geschat_aantal": 1, "voorraadkast": True,
        "candidates": [{"id": "soy", "name": "Sojasaus", "unit_quantity": "150 ml", "price_cents": 199}],
    }]
    pasm = matcher.assemble_from_choices(pantry_wc, [{"index": 0, "product_id": "soy", "aantal": 1}])
    check("voorraadkast-item gemarkeerd (true)", pasm["matched"][0]["voorraadkast"] is True)
    asm_bad = matcher.assemble_from_choices(items_wc, [{"index": 0, "product_id": "bestaat-niet", "aantal": 1}])
    check("valt terug op beste kandidaat bij ongeldig id", asm_bad["matched"][0]["id"] == "big")
    irrel = [{"planned_item": "Spirulina", "zoekterm": "spirulina", "hoeveelheid": "",
              "geschat_aantal": 1,
              "candidates": [{"id": "x", "name": "Cola zero", "unit_quantity": "1 l", "price_cents": 150}]}]
    asm_none = matcher.assemble_from_choices(irrel, [{"index": 0, "product_id": None, "aantal": 1}])
    check("null + irrelevante kandidaat -> unmatched", len(asm_none["unmatched"]) == 1 and not asm_none["matched"])
    heur = matcher.assemble_heuristic(items_wc)
    check("heuristische fallback kiest beste kandidaat", heur["matched"][0]["id"] == "big")

    print("matcher.clean_search_term:")
    check("haakjes eraf", matcher.clean_search_term("Paprika (mix)") == "Paprika")
    check("na komma eraf", matcher.clean_search_term("Eiwitpoeder (whey, naturel)") == "Eiwitpoeder")
    check("meerwoord blijft", matcher.clean_search_term("Rode linzen (voor soep)") == "Rode linzen")

    print("matcher._fallback_terms:")
    check("hoofdwoord als fallback", "tomaten" in matcher._fallback_terms("gehakte tomaten"))
    check("geen fallback bij 1 woord", matcher._fallback_terms("kipfilet") == [])

    print("matcher: null -> eerlijk unmatched (geen verkeerde match):")
    honing_item = [{
        "planned_item": "Honing", "zoekterm": "honing", "hoeveelheid": "", "geschat_aantal": 1,
        "candidates": [{"id": "h1", "name": "Handzeep met honing", "unit_quantity": "1 l", "price_cents": 175}],
    }]
    asm_null = matcher.assemble_from_choices(honing_item, [{"index": 0, "product_id": None, "aantal": 1}])
    check("null -> unmatched (geen handzeep als honing)", not asm_null["matched"] and len(asm_null["unmatched"]) == 1)

    print("matcher.trim_to_budget:")
    cart = [
        {"id": "p1", "name": "Kipfilet", "unit_quantity": "400 g", "count": 10,
         "unit_price_cents": 599, "line_total_cents": 5990},
        {"id": "p2", "name": "Eieren", "unit_quantity": "10 st", "count": 5,
         "unit_price_cents": 329, "line_total_cents": 1645},
        {"id": "p3", "name": "Olijfolie", "unit_quantity": "500 ml", "count": 1,
         "unit_price_cents": 399, "line_total_cents": 399},
    ]
    trimmed_cart, log_ = matcher.trim_to_budget(cart, max_cents=5000)
    new_total = matcher.cart_total_cents(trimmed_cart)
    check("getrimd onder de limiet", new_total <= 5000)
    check("trim raakt eerst de duurste (kipfilet)", any(t["name"] == "Kipfilet" for t in log_))
    check("trim laat goedkoop item (olijfolie) staan", any(m["id"] == "p3" for m in trimmed_cart))
    notrim, log0 = matcher.trim_to_budget(cart, max_cents=99999)
    check("geen trim als binnen budget", log0 == [] and matcher.cart_total_cents(notrim) == matcher.cart_total_cents(cart))

    print("planner._candidate_block (smoke):")
    block = planner._candidate_block(items_wc)
    check("kandidaatblok noemt id's", "id=big" in block and "id=mini" in block)

    print("matcher.normalize_candidate:")
    check("None bij ontbrekende prijs", matcher.normalize_candidate({"id": "x", "name": "y"}) is None)
    check("None bij niet-dict", matcher.normalize_candidate("nope") is None)

    print("planner.validate_plan:")
    plan = planner.validate_plan(
        {
            "samenvatting": "test",
            "dagen": [{"dag": "Ma", "maaltijden": [], "totaal_kcal": 2000, "totaal_eiwit_g": 150}],
            "boodschappenlijst": [{"item": "Kip", "zoekterm": "kip", "hoeveelheid": "1kg", "geschat_aantal": 0}],
        }
    )
    check("geschat_aantal opgehoogd naar >=1", plan["boodschappenlijst"][0]["geschat_aantal"] == 1)

    print("planner.build_user_prompt (vrij verzoek):")
    prompt_free = planner.build_user_prompt(
        cfg, "bulk", macros, request="4x avondeten voor 4 personen, 3 snacks"
    )
    check("vrij verzoek in prompt", "4x avondeten voor 4 personen" in prompt_free)
    check("verzoek krijgt voorrang", "VOORRANG" in prompt_free)
    prompt_std = planner.build_user_prompt(cfg, "bulk", macros)
    check("standaard prompt zonder verzoek", "VOORRANG" not in prompt_std)

    print("telegram_bot._parse_plan_args:")
    from src.telegram_bot import _parse_plan_args
    check("geen args -> default", _parse_plan_args(cfg, []) == (None, None))
    check("modus herkend", _parse_plan_args(cfg, ["bulk"]) == ("bulk", None))
    m, r = _parse_plan_args(cfg, "4x avondeten voor 4 personen".split())
    check("vrije tekst -> request", m is None and r == "4x avondeten voor 4 personen")

    print("config auto-accessors:")
    check("auto_time parse", cfg.auto_time == tuple(map(int, "09:00".split(":"))) or isinstance(cfg.auto_time, tuple))
    check("auto_weekday is int", isinstance(cfg.auto_weekday, int))

    print("orchestrator.parse_slots:")
    slots = orchestrator.parse_slots(
        {"delivery_slots": [{"slot_id": "s1", "window_start": "2026-05-28T17:00:00Z", "window_end": "2026-05-28T19:00:00Z"}]}
    )
    check("slot geparsed", len(slots) == 1 and slots[0]["slot_id"] == "s1")

    print("formatting.format_proposal + menu-tabel + alle producten:")
    fake_proposal = {
        "mode": "bulk",
        "macros": macros,
        "plan": {
            "samenvatting": "lekker",
            "dagen": [{
                "dag": "Ma", "totaal_kcal": 3000, "totaal_eiwit_g": 200,
                "maaltijden": [
                    {"naam": "Havermout met kwark", "type": "ontbijt", "kcal": 500, "eiwit_g": 35},
                    {"naam": "Spaghetti bolognese", "type": "diner", "kcal": 800, "eiwit_g": 50},
                ],
            }],
        },
        # 50 producten -> mag NIET afgekapt worden
        "matched": [{"name": f"Product {i}", "unit_quantity": "500 g", "count": 1, "line_total_cents": 100}
                    for i in range(50)],
        "unmatched": [{"item": "Spirulina"}],
        "total_cents": 5000,
        "slots": slots,
        "over_budget": False,
    }
    text = formatting.format_proposal(fake_proposal)
    check("bevat totaal", "€50.00" in text)
    check("toont menu-maaltijd", "Spaghetti bolognese" in text)
    check("toont ALLE producten (geen afkapping)", "Product 49" in text and "nog " not in text)

    print("formatting.proposal_messages (splitst, alles erin):")
    msgs = formatting.proposal_messages(fake_proposal)
    check("meerdere berichten", len(msgs) >= 2)
    check("elk bericht binnen limiet", all(len(m["text"]) <= formatting.TG_LIMIT for m in msgs))
    joined = "\n".join(m["text"] for m in msgs)
    check("alle 50 producten verdeeld over berichten", "Product 0" in joined and "Product 49" in joined)
    check("menu-maaltijd zichtbaar in berichten", "Spaghetti bolognese" in joined)
    check("menu gegroepeerd per maaltijdtype", "Ontbijt:" in joined or "Diner:" in joined)

    print("nutrition.compute_targets:")
    from src import nutrition
    # Man, cut: kcal moet onder TDEE liggen, eiwit hoog.
    niels = nutrition.compute_targets(
        sex="man", age=30, height_cm=185, weight_kg=105, goal="cut", activity="matig", bodyfat_pct=20
    )
    check("cut kcal < tdee", niels["kcal"] < niels["tdee"])
    check("cut kcal >= bmr (veiligheidsbodem)", niels["kcal"] >= niels["bmr"])
    check("hoog eiwit bij cut", niels["eiwit_g"] >= 150)
    check("macros tellen ongeveer op tot kcal",
          abs((niels["eiwit_g"]*4 + niels["vet_g"]*9 + niels["koolhydraten_g"]*4) - niels["kcal"]) <= 60)
    # Vrouw, bulk: kcal boven TDEE.
    vr = nutrition.compute_targets(
        sex="vrouw", age=28, height_cm=175, weight_kg=64, goal="bulk", activity="licht"
    )
    check("bulk kcal > tdee", vr["kcal"] > vr["tdee"])
    check("man-bmr > vrouw-bmr bij groter lijf", niels["bmr"] > vr["bmr"])

    print("profiles laden uit voorbeeld + targets:")
    from src.profiles import Profiles
    from pathlib import Path
    prof = Profiles.load(Path(__file__).parent / "profiles.example.yaml")
    check("voorbeeld-profiel laadt", prof is not None)
    if prof:
        ctx = prof.planner_context()
        check("twee personen in context", len(ctx["persons"]) == 2)
        check("elke persoon heeft kcal-target", all(p["targets"]["kcal"] > 0 for p in ctx["persons"]))
        check("days uit household", ctx["days"] == 7)

    print("planner.build_profiles_prompt:")
    prompt = planner.build_profiles_prompt(
        prof.planner_context(), request="extra eiwit",
        budget_target_eur=130, cost_conscious=True,
    )
    check("noemt beide personen", all(p["name"] in prompt for p in prof.planner_context()["persons"]))
    check("verzoek krijgt voorrang", "VOORRANG" in prompt)
    check("budget in prompt", "€130" in prompt and "BUDGET" in prompt)
    check("kostenbewust in prompt", "KOSTENBEWUST" in prompt)
    check("volledige dagdekking gevraagd", "ontbijt, lunch, diner" in prompt)
    prompt_nobudget = planner.build_profiles_prompt(prof.planner_context())
    check("geen budgetregel zonder target", "BUDGET" not in prompt_nobudget)

    print("profiles: actief/inactief filter:")
    from src.profiles import Profiles as _Prof
    pr = _Prof(raw={"household": {"days": 7}, "persons": [
        {"name": "A", "sex": "man", "age": 30, "height_cm": 180, "weight_kg": 80, "goal": "cut", "activity": "matig"},
        {"name": "B", "sex": "vrouw", "age": 28, "height_cm": 170, "weight_kg": 65, "goal": "bulk", "activity": "licht", "actief": False},
    ]})
    check("all_persons telt iedereen", len(pr.all_persons) == 2)
    check("persons telt alleen actieve", [p.name for p in pr.persons] == ["A"])
    check("inactieve niet in planner_context", [p["name"] for p in pr.planner_context()["persons"]] == ["A"])
    check("ontbrekende vlag = actief (default true)", pr.all_persons[0].active is True)
    check("weekly_need alleen op actieve", pr.planner_context()["weekly_need"]["daily_kcal"] == pr.persons[0].targets["kcal"])

    print("picnic_client.extract_order_id (geen fout-positief):")
    from src.picnic_client import PicnicClient as _PC
    check("generiek 'shopping_cart' -> None (niet besteld)",
          _PC.extract_order_id({"id": "shopping_cart", "type": "ORDER"}) is None)
    check("leeg/onbekend -> None", _PC.extract_order_id({}) is None)
    check("echt checkout_order_id -> id",
          _PC.extract_order_id({"checkout_order_id": "abc123"}) == "abc123")
    check("echt order_id -> id", _PC.extract_order_id({"order_id": "ord_9"}) == "ord_9")
    check("checkout.id genest -> id", _PC.extract_order_id({"checkout": {"id": "co_7"}}) == "co_7")
    check("checkout met placeholder -> None", _PC.extract_order_id({"checkout": {"id": "cart"}}) is None)

    print("config dry-run override:")
    from src.config import Config as _Cfg
    c_empty = _Cfg(raw={})
    check("zonder safety -> env-default true", c_empty.dry_run(env_default=True) is True)
    check("zonder safety -> env-default false", c_empty.dry_run(env_default=False) is False)
    c_empty.set_dry_run(False)
    check("config override wint van env-default", c_empty.dry_run(env_default=True) is False)
    c_empty.set_dry_run(True)
    check("config override true wint", c_empty.dry_run(env_default=False) is True)

    print("config budget-accessors:")
    check("budget_target_eur is positief getal", isinstance(cfg.budget_target_eur, float) and cfg.budget_target_eur > 0)
    check("cost_conscious is bool", isinstance(cfg.cost_conscious, bool))
    check("max_order_eur is positief getal", cfg.max_order_eur > 0)

    print("nutrition_lookup.parse_nutrition (fixture):")
    from src import nutrition_lookup as nl
    fix = {"c": [{"markdown": "Per 100 g"}, {"markdown": "Energie"}, {"markdown": "235 kJ /"},
                 {"markdown": "kcal"}, {"markdown": "56 kcal"}, {"markdown": "Koolhydraten"},
                 {"markdown": "2,7g"}, {"markdown": "Vet"}, {"markdown": "0,1g"},
                 {"markdown": "Eiwit"}, {"markdown": "10g"}]}
    nf = nl.parse_nutrition(fix)
    check("kcal uit fixture (na 'Energie')", nf.get("kcal") == 56)
    check("eiwit uit fixture (label 'Eiwit')", nf.get("eiwit_g") == 10)
    check("koolhydraten uit fixture", nf.get("koolhydraten_g") == 2.7)
    check("geen tabel -> lege dict", nl.parse_nutrition({"x": "niks"}) == {})

    print("meal_macros.enrich (echte macro's per ingrediënt + per persoon):")
    from src import meal_macros as mm
    _orig_fetch = nl.fetch_nutrition
    nl.fetch_nutrition = lambda api, aid: {"kcal": 56, "eiwit_g": 10}

    class _FakeAPI:
        def _get(self, *a, **k):
            return {}

    class _FakePicnic:
        api = _FakeAPI()
        def search(self, term):
            return [{"items": [{"id": "id_" + term, "name": term, "display_price": 100, "unit_quantity": "100 gram"}]}]

    # Porties per persoon: Niels 200g kwark, Eline 150g; walnoten Niels 30g, Eline 0g.
    plan_in = {"dagen": [{"dag": "Ma", "totaal_kcal": 0, "totaal_eiwit_g": 0, "maaltijden": [
        {"naam": "Kwarkbak", "type": "snack", "kcal": 999, "eiwit_g": 99, "ingredienten": [
            {"naam": "Magere kwark", "zoekterm": "magere kwark",
             "porties": [{"persoon": "Niels", "gram": 200}, {"persoon": "Eline", "gram": 150}]},
            {"naam": "Walnoten", "zoekterm": "walnoten",
             "porties": [{"persoon": "Niels", "gram": 30}, {"persoon": "Eline", "gram": 0}]},
        ]}]}]}
    out = mm.enrich(plan_in, _FakePicnic(), max_item_eur=25, persons=["Niels", "Eline"])
    nl.fetch_nutrition = _orig_fetch
    meal = out["dagen"][0]["maaltijden"][0]
    ing0 = meal["ingredienten"][0]
    check("ingrediënt totaal-gram = som porties (350)", ing0["gram"] == 350)
    check("ingrediënt totaal-kcal (350×56/100=196)", ing0["kcal"] == 196)
    check("per-persoon Niels kwark (200×56/100=112)", ing0["per_persoon"]["Niels"]["kcal"] == 112)
    check("per-persoon Eline kwark (150×56/100=84)", ing0["per_persoon"]["Eline"]["kcal"] == 84)
    # Niels: 112 (kwark) + round(30×56/100=17)=17 -> 129 ; Eline: 84 + 0 = 84
    check("maaltijd per persoon Niels", meal["per_persoon"]["Niels"]["kcal"] == 112 + round(30 * 56 / 100))
    check("maaltijd per persoon Eline", meal["per_persoon"]["Eline"]["kcal"] == 84)
    check("dagtotaal per persoon gevuld",
          out["dagen"][0]["per_persoon"]["Niels"]["kcal"] == meal["per_persoon"]["Niels"]["kcal"])
    check("maaltijd-totaal NIET overschreven (blijft plan)", meal["kcal"] == 999)
    check("bron-product gevuld", ing0.get("bron_product") == "magere kwark")

    # Legacy: ingrediënt met 1 totale 'gram' (geen porties) -> gelijk verdeeld.
    legacy = {"dagen": [{"dag": "Di", "maaltijden": [
        {"naam": "X", "type": "lunch", "kcal": 1, "eiwit_g": 1, "ingredienten": [
            {"naam": "Kwark", "zoekterm": "kwark", "gram": 200}]}]}]}
    nl.fetch_nutrition = lambda api, aid: {"kcal": 56, "eiwit_g": 10}
    lout = mm.enrich(legacy, _FakePicnic(), max_item_eur=25, persons=["A", "B"])
    nl.fetch_nutrition = _orig_fetch
    lmeal = lout["dagen"][0]["maaltijden"][0]
    check("legacy gram verdeeld over personen (elk 100)",
          lmeal["ingredienten"][0]["per_persoon"]["A"]["gram"] == 100)

    print("nutrition: handmatig caloriedoel (kcal_override):")
    ov = nutrition.compute_targets(
        sex="man", age=30, height_cm=185, weight_kg=105, goal="cut",
        activity="matig", bodyfat_pct=20, kcal_override=2200,
    )
    check("override stuurt kcal naar 2200", ov["kcal"] == 2200)
    check("eiwit blijft op niveau bij override", ov["eiwit_g"] >= 150)
    check("koolhydraten blijven op peil (>120g)", ov["koolhydraten_g"] >= 120)
    check("macros kloppen bij override",
          abs((ov["eiwit_g"]*4 + ov["vet_g"]*9 + ov["koolhydraten_g"]*4) - ov["kcal"]) <= 60)

    print("nutrition: gematigde eiwitdoelen:")
    niels2 = nutrition.compute_targets(
        sex="man", age=30, height_cm=185, weight_kg=105, goal="cut", activity="matig", bodyfat_pct=20
    )
    check("Niels eiwit gematigd (~185g, was 220)", 170 <= niels2["eiwit_g"] <= 195)
    check("nog steeds ruim eiwit op cut", niels2["eiwit_g"] >= 150)

    print("onboarding flow (volledige doorloop):")
    from src.onboarding import OnboardingFlow
    flow = OnboardingFlow()
    answers = [
        "Tester", "man", "30", "180", "80", "skip", "cut", "matig",
        "fitness 3x", "omnivoor", "geen", "kip, eieren", "skip",  # persoon 1 klaar
        "nee",                                                     # geen tweede persoon
        "7", "ja", "skip",                                         # huishouden
    ]
    steps_ok = True
    for a in answers:
        ok, err = flow.submit(a)
        if not ok:
            steps_ok = False
            print(f"      onboarding weigerde '{a}': {err}")
            break
    check("alle antwoorden geaccepteerd", steps_ok)
    check("flow afgerond", flow.done)
    if flow.done:
        d = flow.to_profiles_dict()
        check("1 persoon opgeslagen", len(d["persons"]) == 1)
        check("days=7 in resultaat", d["household"]["days"] == 7)
        check("exclude geparsed als lege lijst", d["persons"][0]["exclude"] == [])
        check("prefer geparsed als lijst", d["persons"][0]["prefer"] == ["kip", "eieren"])

    print("onboarding validatie weigert onzin:")
    f2 = OnboardingFlow()
    f2.submit("Naam")  # name ok
    ok_bad, _ = f2.submit("manlijk")  # ongeldige choice voor sex
    check("ongeldige keuze geweigerd", not ok_bad)

    print("formatting met personen (smoke):")
    proposal_persons = dict(fake_proposal)
    proposal_persons["persons"] = [
        {"name": "Niels", "goal": "cut", "targets": niels},
        {"name": "Vriendin", "goal": "bulk", "targets": vr},
    ]
    txt2 = formatting.format_proposal(proposal_persons)
    check("toont persoon Niels", "Niels (cut)" in txt2)
    check("toont persoon Vriendin", "Vriendin (bulk)" in txt2)

    print(f"\n{'🎉 Alles groen' if failures == 0 else f'❌ {failures} test(s) gefaald'}")
    return failures


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "bot":
        run_bot()
    elif cmd == "plan":
        run_plan(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "selftest":
        sys.exit(run_selftest())
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
