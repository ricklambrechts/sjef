import pytest

from sjef.config import Config
from sjef.planning import planner


class MenuLLM:
    """Een andere provider kan hetzelfde contract zonder overerving uitvoeren."""

    def generate_json(self, *, system, prompt, schema):
        assert "voedingscoach" in system
        assert "zonder noten" in prompt
        assert "boodschappenlijst" in schema["properties"]
        return {"boodschappenlijst": [{"item": "Havermout"}]}


def test_plan_uses_injected_provider_and_validates_result():
    config = Config(
        raw={
            "macro_modes": {
                "onderhoud": {
                    "kcal_per_day": 2500,
                    "protein_per_day": 160,
                }
            }
        }
    )
    result = planner.generate_plan(
        config, "onderhoud", llm=MenuLLM(), request="zonder noten"
    )
    assert result["boodschappenlijst"] == [{"item": "Havermout", "geschat_aantal": 1}]


def test_product_choices_use_same_provider_contract():
    class ChoiceLLM:
        def generate_json(self, *, system, prompt, schema):
            assert "Picnic" in system
            assert "id=123" in prompt
            assert "keuzes" in schema["properties"]
            return {"keuzes": [{"index": 0, "product_id": "123", "aantal": 2}]}

    result = planner.choose_products(
        [
            {
                "planned_item": "Melk",
                "geschat_aantal": 1,
                "candidates": [{"id": "123", "name": "Melk", "price_cents": 120}],
            }
        ],
        llm=ChoiceLLM(),
    )
    assert result == [{"index": 0, "product_id": "123", "aantal": 2}]


def test_empty_candidates_need_no_llm_call():
    assert planner.choose_products([], llm=object()) == []


def test_invalid_plan_still_rejected():
    class EmptyLLM:
        def generate_json(self, **kwargs):
            return {"boodschappenlijst": []}

    config = Config(
        raw={
            "macro_modes": {
                "onderhoud": {
                    "kcal_per_day": 2500,
                    "protein_per_day": 160,
                }
            }
        }
    )
    with pytest.raises(ValueError, match="geen boodschappenlijst"):
        planner.generate_plan(config, "onderhoud", llm=EmptyLLM())


@pytest.mark.parametrize("cost_conscious", [False, True])
def test_cost_conscious_product_choice_requests_house_brands(cost_conscious):
    class CaptureLLM:
        def generate_json(self, *, system, prompt, schema):
            assert ("HUISMERKVOORKEUR" in system) is cost_conscious
            if cost_conscious:
                assert "prijs per kilo/liter" in system
                assert "expliciete merkvoorkeur" in system
            return {"keuzes": []}

    planner.choose_products(
        [
            {
                "planned_item": "Melk",
                "geschat_aantal": 1,
                "candidates": [
                    {"id": "milk", "name": "Picnic melk", "price_cents": 120}
                ],
            }
        ],
        llm=CaptureLLM(),
        cost_conscious=cost_conscious,
    )


def test_cost_conscious_menu_keeps_search_terms_brand_neutral():
    instruction = " ".join(planner._budget_block(None, True))
    assert "huismerk" in instruction
    assert "merkneutrale zoektermen" in instruction
    assert "huismerk" not in " ".join(planner._budget_block(None, False))
