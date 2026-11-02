from types import SimpleNamespace

import pytest

from sjef.config import Config
from sjef.picnic.picnic_client import PicnicClient
from sjef.planning import planner


def product(pid, name, price, quantity):
    return dict(id=pid, name=name, display_price=price, unit_quantity=quantity)


def promotion_tile(pid="deal", label="nu €1.50"):
    return {
        "type": "PML",
        "analytics": {
            "contexts": [
                {
                    "data": {
                        "promotion_id": "promo",
                        "promotion_label": label,
                        "price": 150,
                        "strikethrough_price": 250,
                    }
                }
            ]
        },
        "content": {
            "type": "SELLING_UNIT_TILE",
            "sellingUnit": product(pid, "Merk volkoren pasta", 150, "500 gram"),
        },
    }


def test_picnic_extracts_only_promotions_and_deduplicates():
    client = PicnicClient.__new__(PicnicClient)

    def get(path, *, add_picnic_headers):
        assert path == "/pages/promo-page-all-promos-redirect"
        assert add_picnic_headers
        return {
            "layout": {
                "body": [
                    promotion_tile(),
                    [promotion_tile()],
                    {
                        "content": {
                            "sellingUnit": product("regular", "Melk", 150, "1 l")
                        }
                    },
                ]
            }
        }

    client.api = SimpleNamespace(_get=get)
    result = client.get_promotions()
    assert len(result) == 1
    assert result[0]["id"] == "deal"
    assert result[0]["promotion_label"] == "nu €1.50"
    assert result[0]["display_price"] == 150
    assert result[0]["original_price"] == 250


def test_picnic_rejects_error_payload_instead_of_reporting_no_deals():
    client = PicnicClient.__new__(PicnicClient)
    client.api = SimpleNamespace(_get=lambda *a, **kw: {"error": {"code": "FAILED"}})
    with pytest.raises(ValueError):
        client.get_promotions()


@pytest.mark.parametrize(
    "price,quantity,expected",
    [
        (150, "500 gram", (300, "kg")),
        (150, "0,5 kg", (300, "kg")),
        (200, "2 x 250 ml", (400, "l")),
        (240, "6 stuks", (40, "stuk")),
        (150, "ca. 500 gram", None),
        (150, "1 bos", None),
        (0, "1 kg", None),
        (150, "0 gram", None),
    ],
)
def test_price_comparison_normalizes_pack_sizes(price, quantity, expected):
    from sjef.planning.offers import unit_price

    assert unit_price(product("x", "Product", price, quantity)) == expected


class OfferLLM:
    def __init__(self, comparisons=None):
        self.comparisons = comparisons or ["house"]

    def generate_json(self, *, system, prompt, schema):
        if "zoekopdrachten" in schema["properties"]:
            return {"zoekopdrachten": [{"id": "deal", "zoekterm": "volkoren pasta"}]}
        assert "Picnic volkoren pasta" in prompt
        return {"vergelijkingen": [{"id": "deal", "huismerk_ids": self.comparisons}]}


@pytest.mark.parametrize(
    "house_price,house_quantity,accepted",
    [
        (200, "500 gram", True),
        (300, "1 kg", False),
        (250, "1 kg", False),
        (200, "1 stuk", False),
    ],
)
def test_only_deals_strictly_cheaper_than_comparable_house_brand_are_selected(
    house_price, house_quantity, accepted
):
    from sjef.planning.offers import find_worthwhile_offers

    deal = {
        **product("deal", "Merk volkoren pasta", 150, "500 gram"),
        "promotion_label": "nu €1.50",
        "original_price": 250,
    }
    picnic = SimpleNamespace(
        get_promotions=lambda: [deal],
        search=lambda term: [
            product("house", "Picnic volkoren pasta", house_price, house_quantity)
        ],
    )
    result = find_worthwhile_offers(picnic, OfferLLM(), max_item_eur=25)
    assert bool(result) is accepted
    if accepted:
        assert result[0]["id"] == "deal"
        assert result[0]["unit_price_cents"] == 300
        assert result[0]["house_brand_unit_price_cents"] == 400


def test_unknown_comparator_ids_cannot_make_an_offer_eligible():
    from sjef.planning.offers import find_worthwhile_offers

    picnic = SimpleNamespace(
        get_promotions=lambda: [
            {
                **product("deal", "Pasta", 150, "500 g"),
                "promotion_label": "nu €1.50",
                "original_price": 250,
            }
        ],
        search=lambda term: [product("house", "Picnic volkoren pasta", 200, "500 g")],
    )
    assert find_worthwhile_offers(picnic, OfferLLM(["invented"]), max_item_eur=25) == []


def test_cheapest_house_brand_beyond_twenty_results_still_counts():
    from sjef.planning.offers import find_worthwhile_offers

    picnic = SimpleNamespace(
        get_promotions=lambda: [
            {
                **product("deal", "Pasta", 150, "500 g"),
                "promotion_label": "nu €1.50",
                "original_price": 250,
            }
        ],
        search=lambda term: (
            [product("house", "Picnic volkoren pasta", 200, "500 g")]
            + [product(str(i), "Merk pasta", 400, "500 g") for i in range(19)]
            + [product("cheap", "Picnic volkoren pasta", 100, "500 g")]
        ),
    )
    assert (
        find_worthwhile_offers(picnic, OfferLLM(["house", "cheap"]), max_item_eur=25)
        == []
    )


def test_matching_keeps_verified_offer_and_house_brand_with_fresh_prices():
    from sjef.planning.matcher import gather_candidates

    picnic = SimpleNamespace(
        search=lambda term: (
            [product(str(i), "Pasta", 400, "500 g") for i in range(10)]
            + [
                product("deal", "Merk pasta", 160, "500 g"),
                product("house", "Picnic pasta", 140, "500 g"),
            ]
        )
    )
    groups, _ = gather_candidates(
        picnic, [{"item": "Pasta"}], 25, preferred_ids={"deal", "house", "missing"}
    )
    candidates = {c["id"]: c["price_cents"] for c in groups[0]["candidates"]}
    assert candidates["deal"] == 160
    assert candidates["house"] == 140
    assert "missing" not in candidates


@pytest.mark.parametrize("label", ["1+1 gratis", "2 voor €3", "2e halve prijs"])
def test_conditional_discounts_are_not_mistaken_for_single_pack_discounts(label):
    from sjef.planning.offers import find_worthwhile_offers

    picnic = SimpleNamespace(
        get_promotions=lambda: [
            {
                **product("deal", "Pasta", 150, "500 g"),
                "promotion_label": label,
                "original_price": 250,
            }
        ]
    )
    assert find_worthwhile_offers(picnic, object(), max_item_eur=25) == []


@pytest.mark.parametrize(
    "profiles_ctx", [None, {"days": 3, "persons": [{"summary": "A", "name": "A"}]}]
)
def test_verified_offers_reach_both_menu_modes(profiles_ctx):
    class CaptureLLM:
        def generate_json(self, *, system, prompt, schema):
            assert "deal" in prompt
            assert "huismerk" in prompt.lower()
            assert "voedingsdoelen" in prompt.lower()
            return {"boodschappenlijst": [{"item": "Pasta"}]}

    planner.generate_plan(
        Config(
            raw={
                "macro_modes": {
                    "onderhoud": {"kcal_per_day": 2000, "protein_per_day": 100}
                }
            }
        ),
        "onderhoud",
        CaptureLLM(),
        profiles_ctx=profiles_ctx,
        offers=[{"id": "deal", "name": "Pasta", "unit_price_cents": 300}],
    )


def test_offer_preference_defaults_off_and_roundtrips(tmp_path):
    assert Config().use_offers is False
    config = Config(raw={"budget": {"cost_conscious": False, "use_offers": True}})
    config.save(tmp_path / "config.yaml")
    loaded = Config.load(tmp_path / "config.yaml")
    assert loaded.use_offers is True
    assert loaded.cost_conscious is False


@pytest.mark.parametrize(
    "enabled,broken", [(False, False), (True, False), (True, True)]
)
def test_proposal_uses_offers_before_menu_and_survives_failure(
    monkeypatch, enabled, broken
):
    from sjef.interfaces.formatting import format_proposal
    from sjef.planning import orchestrator

    class Picnic:
        def get_promotions(self):
            assert enabled, "Disabled preference must not fetch promotions"
            if broken:
                raise RuntimeError("Unavailable")
            return [
                {
                    **product("deal", "Merk volkoren pasta", 150, "500 g"),
                    "promotion_label": "nu €1.50",
                    "original_price": 250,
                }
            ]

        def search(self, term):
            return [
                product("house", "Picnic volkoren pasta", 200, "500 g"),
                product("deal", "Merk volkoren pasta", 150, "500 g"),
            ]

        def get_delivery_slots(self):
            return {"slots": []}

    class ProposalLLM(OfferLLM):
        def generate_json(self, *, system, prompt, schema):
            if "boodschappenlijst" in schema["properties"]:
                assert ("AANBIEDINGEN:" in prompt) is (enabled and not broken)
                return {
                    "boodschappenlijst": [
                        {"item": "Pasta", "zoekterm": "volkoren pasta"}
                    ]
                }
            if "keuzes" in schema["properties"]:
                if enabled and not broken:
                    assert "aanbieding" in prompt.lower()
                return {"keuzes": [{"index": 0, "product_id": "deal", "aantal": 1}]}
            return super().generate_json(system=system, prompt=prompt, schema=schema)

    monkeypatch.setattr(orchestrator.Profiles, "load", lambda: None)
    monkeypatch.setattr(orchestrator, "create_llm", lambda *a, **kw: ProposalLLM())
    monkeypatch.setattr(orchestrator.meal_macros, "enrich", lambda plan, *a, **kw: plan)
    config = Config(
        raw={
            "budget": {"use_offers": enabled},
            "macro_modes": {
                "onderhoud": {"kcal_per_day": 2000, "protein_per_day": 100}
            },
        }
    )
    result = orchestrator.build_proposal(config, object(), Picnic(), mode="onderhoud")
    assert result["matched"]
    assert bool(result.get("offers")) is (enabled and not broken)
    if enabled:
        assert result["offers_message"]
        assert result["offers_message"] in format_proposal(result)
    if broken:
        assert "zonder aanbiedingen" in result["offers_message"]
