"""Compacte dagkaarten met recepten en voedingsdetails."""

from html import escape

import pandas as pd
import streamlit as st

MENU_CSS = """
<style>
.sjef-day {color:#286344; font-size:1.3rem; font-weight:700; margin:0 0 .5rem;}
.sjef-meal {border-top:1px solid #ece6da; padding:1rem 0 .25rem;}
.sjef-meal small {color:#687469; text-transform:uppercase; letter-spacing:.09em; font-size:.7rem;}
.sjef-meal h4 {font-size:1.05rem; font-weight:600; margin:.25rem 0; padding:0; color:#243d2e;}
</style>
"""


def macro_summary(values):
    def value(key):
        v = values.get(key)
        return "—" if v is None else str(v)

    return (
        f"{value('kcal')} kcal · {value('eiwit_g')} g eiwit · "
        f"{value('koolhydraten_g')} g koolhydraten"
    )


def render_week_menu(plan: dict, person_names: list[str]) -> None:
    st.markdown(MENU_CSS, unsafe_allow_html=True)
    st.subheader("Weekmenu")
    st.caption(
        "Je maaltijden per dag. Open een recept voor ingrediënten en bereiding. "
        "Voedingswaarden komen van Picnic; ontbrekende etiketwaarden kunnen totalen "
        "onvolledig maken. Onbekende koolhydraten tonen we als ‘—’."
    )
    days = plan.get("dagen") or []
    for offset in range(0, len(days), 2):
        columns = st.columns(2)
        for col, day in zip(columns, days[offset : offset + 2], strict=False):
            with col, st.container(border=True):
                st.markdown(
                    f'<div class="sjef-day">{escape(str(day.get("dag", "Dag")))}</div>',
                    unsafe_allow_html=True,
                )
                day_pp = day.get("per_persoon") or {}
                if day_pp:
                    for name in person_names or list(day_pp):
                        if name in day_pp:
                            st.caption(f"{name} · {macro_summary(day_pp[name])}")
                else:
                    st.caption(
                        macro_summary(
                            {
                                "kcal": day.get("totaal_kcal"),
                                "eiwit_g": day.get("totaal_eiwit_g"),
                                "koolhydraten_g": day.get("ingr_koolhydraten_g"),
                            }
                        )
                    )
                for meal in day.get("maaltijden") or []:
                    name = str(meal.get("naam", "Maaltijd"))
                    st.markdown(
                        f'<div class="sjef-meal"><small>{escape(str(meal.get("type", "")))}</small>'
                        f"<h4>{escape(name)}</h4></div>",
                        unsafe_allow_html=True,
                    )
                    for person, values in (meal.get("per_persoon") or {}).items():
                        st.caption(f"{person} · {macro_summary(values)}")
                    if not meal.get("per_persoon"):
                        st.caption(
                            macro_summary(
                                {
                                    "kcal": meal.get("ingr_kcal"),
                                    "eiwit_g": meal.get("ingr_eiwit"),
                                    "koolhydraten_g": meal.get("ingr_koolhydraten_g"),
                                }
                            )
                        )
                    with st.expander(f"Recept · {name}"):
                        ingredients = meal.get("ingredienten") or []
                        st.markdown("**Ingrediënten**")
                        if not ingredients:
                            st.caption(
                                "Bij deze maaltijd zijn geen ingrediënten opgeslagen."
                            )
                        for ingredient in ingredients:
                            portions = ingredient.get("porties") or []
                            amounts = " · ".join(
                                f"{p['persoon']}: {p['gram']} g/ml" for p in portions
                            )
                            if not amounts:
                                amounts = " · ".join(
                                    f"{p}: {v.get('gram', '—')} g/ml"
                                    for p, v in (
                                        ingredient.get("per_persoon") or {}
                                    ).items()
                                )
                            if not amounts:
                                amounts = f"{ingredient.get('gram', '—')} g/ml totaal"
                            st.markdown(
                                f"- **{ingredient.get('naam', '')}** — {amounts}"
                            )
                        st.markdown("**Bereiding**")
                        steps = meal.get("bereiding") or []
                        if steps:
                            st.markdown(
                                "\n\n".join(
                                    f"{index}. {step}"
                                    for index, step in enumerate(steps, 1)
                                )
                            )
                        else:
                            st.caption(
                                "Dit opgeslagen menu bevat geen bereidingsstappen. "
                                "Maak een nieuw weekmenu om recepten te ontvangen."
                            )
                    if ingredients:
                        with st.expander(f"Voedingsdetails · {name}"):
                            rows = []
                            for ingredient in ingredients:
                                row = {
                                    "Ingrediënt": ingredient.get("naam", ""),
                                    "Gram/ml (tot.)": ingredient.get("gram"),
                                    "Koolhydraten (g)": ingredient.get(
                                        "koolhydraten_g"
                                    ),
                                    "Picnic-product": ingredient.get("bron_product")
                                    or "—",
                                }
                                for person, values in (
                                    ingredient.get("per_persoon") or {}
                                ).items():
                                    row[person] = (
                                        f"{values.get('gram', '—')} g/ml · {macro_summary(values)}"
                                    )
                                rows.append(row)
                            st.dataframe(
                                pd.DataFrame(rows),
                                hide_index=True,
                                use_container_width=True,
                            )
