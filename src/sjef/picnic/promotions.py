"""Lees promotietegels uit de Picnic-pagina 'Alle acties'."""

from python_picnic_api2.models.pml import walk


def parse_promotions(page: dict) -> list[dict]:
    # Ook een gewijzigde response moet zichtbaar worden, niet als 'geen acties'.
    if (
        not isinstance(page, dict)
        or page.get("error")
        or not any(key in page for key in ("layout", "body"))
    ):
        raise ValueError("Picnic-aanbiedingenpagina kon niet worden gelezen")
    products = {}
    for node in walk(page):
        content = node.get("content") or {}
        if not isinstance(content, dict):
            continue
        product = content.get("sellingUnit")
        if not isinstance(product, dict) or not product.get("id"):
            continue
        analytics = node.get("analytics") or {}
        if not isinstance(analytics, dict):
            continue
        for context in analytics.get("contexts") or []:
            if not isinstance(context, dict):
                continue
            promo = context.get("data")
            if not isinstance(promo, dict) or not promo.get("promotion_id"):
                continue
            products[str(product["id"])] = {
                **product,
                "display_price": promo.get("price", product.get("display_price")),
                "promotion_label": promo.get("promotion_label", ""),
                "original_price": promo.get("strikethrough_price")
                if promo.get("show_strikethrough_price") is not False
                else None,
            }
    return list(products.values())
