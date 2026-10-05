"""Phone Place Kenya (WooCommerce, Merto theme): phones, tablets and accessories."""

from .registry import register
from .woocommerce import WooCommerceScraper


@register
class PhonePlace(WooCommerceScraper):
    name = "Phone Place"
    base_url = "https://www.phoneplacekenya.com"
