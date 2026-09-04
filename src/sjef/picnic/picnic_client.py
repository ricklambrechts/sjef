"""Wrapper rond python-picnic-api2.

Voegt de twee endpoints toe die de library mist maar die we nodig hebben om
end-to-end te bestellen: een bezorgslot boeken en de order bevestigen. Deze
roepen we rechtstreeks aan via de interne sessie van de library (zelfde
Picnic-servers, geen externe hosts).

VEILIGHEID: alle methodes die geld kosten of een order plaatsen controleren
`dry_run`. In dry-run worden ze NIET uitgevoerd; ze loggen alleen wat ze zouden
doen. Echt bestellen kan pas als dry_run=False én er expliciet is goedgekeurd.
"""

from __future__ import annotations

import logging

from python_picnic_api2 import PicnicAPI

from sjef.config import ROOT

log = logging.getLogger(__name__)

TOKEN_FILE = ROOT / "state" / "picnic_auth_token.txt"


class PicnicClient:
    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        country_code: str = "NL",
        auth_token: str | None = None,
        dry_run: bool = True,
    ):
        self.dry_run = dry_run
        self._country_code = country_code

        # Geef een bestaande token voorrang: dan is er geen 2FA nodig.
        token = auth_token or self._load_token()
        if token:
            self.api = PicnicAPI(auth_token=token, country_code=country_code)
            if not self.api.logged_in():
                log.warning("Opgeslagen Picnic-token is verlopen; nieuwe login nodig.")
                self.api = self._login(username, password, country_code)
        else:
            self.api = self._login(username, password, country_code)

        self._persist_token()

    # ---------------------------------------------------------------- auth
    @staticmethod
    def _login(username, password, country_code) -> PicnicAPI:
        if not (username and password):
            raise RuntimeError(
                "Geen geldige Picnic-token en geen username/password. "
                "Draai eerst: uv run sjef picnic-login"
            )
        # NB: login() gooit Picnic2FARequired als 2FA aan staat. De interactieve
        # 2FA-stap zit in login_setup.py, niet hier, zodat de bot nooit om een
        # SMS-code hoeft te vragen tijdens een geautomatiseerde run.
        return PicnicAPI(
            username=username, password=password, country_code=country_code
        )

    def _load_token(self) -> str | None:
        if TOKEN_FILE.exists():
            tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
            return tok or None
        return None

    def _persist_token(self) -> None:
        token = getattr(self.api.session, "auth_token", None)
        if token:
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(token, encoding="utf-8")

    # --------------------------------------------------------------- lezen
    def search(self, term: str) -> list[dict]:
        """Zoek producten. Geeft een platte lijst van article-dicts terug."""
        return self.api.search(term)

    def get_cart(self) -> dict:
        return self.api.get_cart()

    def get_delivery_slots(self) -> dict:
        return self.api.get_delivery_slots()

    def get_user(self) -> dict:
        return self.api.get_user()

    # ----------------------------------------------------- mandje wijzigen
    def clear_cart(self) -> dict | None:
        if self.dry_run:
            log.info("[DRY-RUN] clear_cart() overgeslagen")
            return None
        return self.api.clear_cart()

    def add_product(self, product_id: str, count: int = 1) -> dict | None:
        if self.dry_run:
            log.info(
                "[DRY-RUN] add_product(%s, count=%s) overgeslagen", product_id, count
            )
            return None
        return self.api.add_product(product_id, count)

    # ----------------------------------------------- order plaatsen (geld!)
    def set_delivery_slot(self, slot_id: str) -> dict | None:
        """Boek een bezorgslot. Niet in de library; rechtstreeks via /cart/set_delivery_slot."""
        if self.dry_run:
            log.info("[DRY-RUN] set_delivery_slot(%s) overgeslagen", slot_id)
            return None
        # _post zit op de echte Picnic-storefront API (zie session.py audit).
        return self.api._post("/cart/set_delivery_slot", {"slot_id": slot_id})

    def confirm_order(self, order_id: str) -> dict | None:
        """Bevestig en plaats de order definitief. Hierna loopt de incasso.

        Niet in de library; rechtstreeks via /cart/checkout/order/{id}/confirm.
        """
        if self.dry_run:
            log.info(
                "[DRY-RUN] confirm_order(%s) overgeslagen — er wordt NIET besteld",
                order_id,
            )
            return None
        return self.api._post(f"/cart/checkout/order/{order_id}/confirm")

    # -------------------------------------------------------------- helper
    # Generieke/placeholder-id's die GEEN echt order-id zijn. Het cart-object
    # heeft bijvoorbeeld vast id="shopping_cart"; dat mag nooit als bewijs van
    # een geplaatste order gelden (anders krijg je een fout-positieve "Besteld!").
    _NON_ORDER_IDS = {"shopping_cart", "cart", "checkout", ""}

    @classmethod
    def extract_order_id(cls, cart: dict) -> str | None:
        """Haal een ECHT order/checkout-id uit een cart-response, of None.

        None betekent: niet bevestigd kunnen vaststellen → de beller mag NIET
        'besteld' melden, maar moet de gebruiker naar de Picnic-app verwijzen.
        """
        if not isinstance(cart, dict):
            return None
        # Alleen expliciete order-id-velden tellen; NIET het generieke 'id'
        # (dat is 'shopping_cart').
        for key in ("checkout_order_id", "order_id"):
            val = cart.get(key)
            if val and str(val).lower() not in cls._NON_ORDER_IDS:
                return str(val)
        checkout = cart.get("checkout") or {}
        if isinstance(checkout, dict):
            val = checkout.get("id") or checkout.get("order_id")
            if val and str(val).lower() not in cls._NON_ORDER_IDS:
                return str(val)
        return None
