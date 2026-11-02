from streamlit.testing.v1 import AppTest


def menu_app(meal):
    app = AppTest.from_string("""
import streamlit as st
from sjef.interfaces.week_menu import render_week_menu
render_week_menu({"dagen": [{"dag": "Maandag", "maaltijden": [st.session_state.meal]}]}, ["Sam"])
""")
    app.session_state.meal = meal
    return app.run()


def test_recipe_shows_steps_and_original_portions_without_nutrition():
    app = menu_app(
        {
            "naam": "Havermout",
            "type": "ontbijt",
            "ingredienten": [
                {"naam": "Havermout", "porties": [{"persoon": "Sam", "gram": 60}]}
            ],
            "bereiding": ["Verwarm de havermout met water.", "Serveer in een kom."],
        }
    )
    assert not app.exception
    text = "\n".join(item.value for item in app.markdown)
    assert "Havermout" in text
    assert "1. Verwarm de havermout met water." in text
    assert "2. Serveer in een kom." in text
    assert "Sam: 60 g/ml" in text
    assert app.expander[0].label == "Recept · Havermout"


def test_saved_menu_without_recipe_still_renders():
    app = menu_app({"naam": "Soep", "type": "lunch"})
    assert not app.exception
    assert any("geen bereidingsstappen" in item.value for item in app.caption)


def test_legacy_meal_keeps_calculated_carbohydrates():
    app = menu_app({"naam": "Soep", "type": "lunch", "ingr_koolhydraten_g": 32})
    assert not app.exception
    assert any("32 g koolhydraten" in item.value for item in app.caption)
