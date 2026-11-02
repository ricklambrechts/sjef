from copy import deepcopy

import pytest

from sjef.planning import meal_macros


@pytest.mark.parametrize("carbs", [20, 0, None])
def test_carbohydrates_per_portion_meal_and_day(monkeypatch, carbs):
    monkeypatch.setattr(
        meal_macros,
        "_nutrition_map",
        lambda *args: {
            "rijst": {
                "product": "Rijst",
                "per100g": {"kcal": 100, "eiwit_g": 4, "koolhydraten_g": carbs},
            }
        },
    )
    ingredient = {
        "naam": "rijst",
        "porties": [{"persoon": "A", "gram": 150}, {"persoon": "B", "gram": 50}],
    }
    plan = {
        "dagen": [
            {
                "maaltijden": [
                    {"ingredienten": [deepcopy(ingredient)]},
                    {"ingredienten": [deepcopy(ingredient)]},
                ]
            }
        ]
    }
    meal_macros.enrich(plan, None, 10, persons=["A", "B"])
    day = plan["dagen"][0]
    meal = day["maaltijden"][0]
    ing = meal["ingredienten"][0]
    assert ing["koolhydraten_g"] == (carbs * 2 if carbs is not None else None)
    assert ing["per_persoon"]["A"]["koolhydraten_g"] == (
        carbs * 1.5 if carbs is not None else None
    )
    assert meal["per_persoon"]["B"]["koolhydraten_g"] == (
        carbs * 0.5 if carbs is not None else None
    )
    assert day["per_persoon"]["A"]["koolhydraten_g"] == (
        carbs * 3 if carbs is not None else None
    )
    assert meal["ingr_koolhydraten_g"] == (carbs * 2 if carbs is not None else None)


def test_missing_carbs_only_affect_people_eating_that_ingredient(monkeypatch):
    monkeypatch.setattr(
        meal_macros,
        "_nutrition_map",
        lambda *args: {
            "rijst": {"per100g": {"kcal": 100, "koolhydraten_g": 20}},
            "groente": {"per100g": {}},
        },
    )
    plan = {
        "dagen": [
            {
                "maaltijden": [
                    {
                        "ingredienten": [
                            {
                                "naam": "rijst",
                                "porties": [
                                    {"persoon": "A", "gram": 100},
                                    {"persoon": "B", "gram": 100},
                                ],
                            },
                            {
                                "naam": "groente",
                                "porties": [{"persoon": "A", "gram": 50}],
                            },
                        ]
                    }
                ]
            }
        ]
    }
    meal_macros.enrich(plan, None, 10, persons=["A", "B"])
    day = plan["dagen"][0]
    assert day["per_persoon"]["A"]["koolhydraten_g"] is None
    assert day["per_persoon"]["B"]["koolhydraten_g"] == 20
    assert day["ingr_koolhydraten_g"] is None


def test_carbs_are_independent_of_energy_label(monkeypatch):
    monkeypatch.setattr(
        meal_macros,
        "_nutrition_map",
        lambda *args: {
            "rijst": {"per100g": {"koolhydraten_g": 20}},
        },
    )
    plan = {
        "dagen": [
            {
                "maaltijden": [
                    {
                        "ingredienten": [
                            {
                                "naam": "rijst",
                                "porties": [{"persoon": "A", "gram": 50}],
                            },
                        ]
                    }
                ]
            }
        ]
    }
    meal_macros.enrich(plan, None, 10, persons=["A"])
    assert plan["dagen"][0]["per_persoon"]["A"]["koolhydraten_g"] == 10


def test_empty_meal_does_not_make_day_total_look_complete(monkeypatch):
    monkeypatch.setattr(
        meal_macros,
        "_nutrition_map",
        lambda *args: {
            "rijst": {"per100g": {"kcal": 100, "koolhydraten_g": 20}},
        },
    )
    plan = {
        "dagen": [
            {
                "maaltijden": [
                    {
                        "ingredienten": [
                            {
                                "naam": "rijst",
                                "porties": [{"persoon": "A", "gram": 100}],
                            }
                        ]
                    },
                    {"ingredienten": []},
                ]
            }
        ]
    }
    meal_macros.enrich(plan, None, 10, persons=["A"])
    day = plan["dagen"][0]
    assert day["maaltijden"][1]["ingr_koolhydraten_g"] is None
    assert day["per_persoon"]["A"]["koolhydraten_g"] is None
    assert day["ingr_koolhydraten_g"] is None
