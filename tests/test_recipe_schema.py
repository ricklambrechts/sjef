import pytest
from jsonschema import ValidationError, validate

from sjef.planning.planner import PLAN_SCHEMA


def test_new_meals_require_nonempty_preparation_steps():
    schema = PLAN_SCHEMA["properties"]["dagen"]["items"]["properties"]["maaltijden"][
        "items"
    ]
    meal = {
        "naam": "Soep",
        "type": "lunch",
        "kcal": 200,
        "eiwit_g": 10,
        "ingredienten": [],
    }
    with pytest.raises(ValidationError):
        validate(meal, schema)
    meal["bereiding"] = []
    with pytest.raises(ValidationError):
        validate(meal, schema)
    meal["bereiding"] = ["Breng water aan de kook."]
    validate(meal, schema)
