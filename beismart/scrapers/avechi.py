"""Avechi Kenya (WooCommerce, Merto theme)."""

from .registry import register
from .woocommerce import WooCommerceScraper


@register
class Avechi(WooCommerceScraper):
    name = "Avechi"
    base_url = "https://avechi.co.ke"
