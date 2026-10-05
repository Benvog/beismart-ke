"""Working out which listings are the same product.

A title is reduced to four facts: brand, model, size-or-storage, and new versus refurbished. Two listings
are grouped only when all four are known and equal. When anything is unclear the listing stays on its own:
a wrong merge (two different TVs priced as one) is worse than a missed one."""

import re
from dataclasses import dataclass
from typing import Optional

BRANDS = (
    "samsung", "apple", "hisense", "lg", "tcl", "sony", "skyworth", "vitron", "syinix", "nunix", "xiaomi", "redmi",
    "tecno", "infinix", "itel", "oppo", "vivo", "realme", "nokia", "oneplus", "huawei", "honor", "motorola",
    "philips", "ninja", "tefal", "kenwood", "ramtons", "von", "bruhm", "mika", "haier", "midea", "beko", "bosch",
    "whirlpool", "panasonic", "sharp", "toshiba", "hotpoint", "tornado", "russell hobbs", "black+decker", "nutricook",
    "hp", "dell", "lenovo", "asus", "acer", "microsoft", "jbl", "anker", "soundcore", "sennheiser", "bose",
    "canon", "nikon", "gopro", "dyson", "zylo", "chefman", "cosori", "instant", "gaabor",
    "globalstar", "glamstar", "ecomax", "sanford", "oraimo", "shokz", "marshall", "braun", "skullcandy",
)
_BRAND_RE = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(b) for b in sorted(BRANDS, key=len, reverse=True)) + r")(?![a-z0-9])")

_REFURB_RE = re.compile(r"(?<![a-z0-9])(refurbished|renewed|pre-?owned|used|ex-?uk|second[- ]hand|open box|grade ?[abc]|bh ?\d{2}%?)(?![a-z0-9])", re.I)

# Tokens that look like model codes but are specifications.
_SPEC_RE = re.compile(
    r"^(?:\d+(?:k|g|gb|tb|hz|w|kw|l|ml|kg|mm|mp|mah|inch|in|v|pcs|pc|qt|btu|rpm|fps)"
    r"|[2-8]k|[2-5]g|hdr\d*\+?|dolby\w*|ddr\d|usb\d?[a-z]?|hdmi\d?|wifi\d?|bt\d(?:\.\d)?|bluetooth\d?|uhd|fhd|qled|oled|"
    r"a1\d|m[1-4]|h26[45]|ip\d{2}|ipx\d|1080p|720p|2160p|\d+x\d+)$",
    re.I,
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9/+\-]*[A-Za-z0-9]|[A-Za-z0-9]")
_SIZE_RE = re.compile(r"(\d{2,3})\s*(?:\"|''|”|inch(?:es)?\b|-inch\b)", re.I)
_STORAGE_RE = re.compile(r"(\d{2,4})\s*(gb|tb)\b", re.I)
_IPHONE_RE = re.compile(r"iphone\s*(\d{1,2}|se|x[rsm]?|xs)\s*(pro ?max|pro|plus|mini|e)?\b", re.I)
_GALAXY_RE = re.compile(r"galaxy\s+((?:s\d{2}|[amf]\d{2}|z\s?(?:fold|flip)\s?\d?)[a-z]?)(?![a-z0-9])(?:\s*(ultra|plus|fe|\+))?", re.I)
_REGION_PREFIX = re.compile(r"^(?:UA|QA|UE|QE|SM)")
# TV series codes: 4-digit series (F6000, U8000, H5000) or 1-2 digit QLED series (Q7F, QN85F).
_SERIES_4 = re.compile(r"([A-Z]{1,2}\d{4})")
_SERIES_2 = re.compile(r"([A-Z]{1,3}\d{1,2}[A-Z])")


@dataclass(frozen=True)
class ProductKey:
    brand: str
    model: str
    variant: str          # "43in", "128gb", "" when the product has no size or storage
    condition: str        # "new" or "refurbished"

    def __str__(self) -> str:
        return " | ".join(p for p in (self.brand, self.model, self.variant, self.condition) if p)


def _size(title: str) -> Optional[int]:
    sizes = [int(m) for m in _SIZE_RE.findall(title)]
    sizes = [s for s in sizes if 10 <= s <= 120]
    return sizes[0] if sizes else None


def _storage(title: str) -> Optional[str]:
    options = [(int(n) * (1024 if u.lower() == "tb" else 1), u.lower()) for n, u in _STORAGE_RE.findall(title)]
    options = [gb for gb, _ in options if gb >= 32]          # below 32GB is RAM, not storage
    return f"{max(options)}gb" if options else None


def _code_tokens(title: str) -> list[str]:
    out = []
    for token in _TOKEN_RE.findall(title):
        if "+" in token:
            continue                                          # "ROM+8GB", "4GB+128GB": specifications
        t = token.upper().replace("-", "").replace("/", "")
        if len(t) < 3 or not re.search(r"[A-Z]", t) or not re.search(r"\d", t) or _SPEC_RE.match(t):
            continue
        out.append(t)
    return out


def _tv_series(code: str) -> Optional[str]:
    """UA43U8000FUXKE, 43U8000, U8000F -> U8000;  QA55Q8FAAU -> Q8F."""
    c = _REGION_PREFIX.sub("", code)
    c = re.sub(r"^\d{2,3}(?=[A-Z])", "", c)               # leading size digits
    c = re.sub(r"^[A-Z]{1,2}(\d{2,3})(?=[A-Z]\d)", "", c)  # prefix such as 'UA43' left after region strip
    m = _SERIES_4.match(c) or _SERIES_2.match(c)
    return m.group(1) if m else None


def model_of(title: str, brand: str) -> Optional[str]:
    lower = title.lower()
    if m := _IPHONE_RE.search(lower):
        return f"iphone {m.group(1)}{' ' + re.sub(r'[ ]', '', m.group(2)).replace('promax', 'pro max') if m.group(2) else ''}".strip()
    if m := _GALAXY_RE.search(lower):
        return "galaxy " + re.sub(r"\s+", "", m.group(1)) + (f" {m.group(2).replace('+', 'plus')}" if m.group(2) else "")
    codes = _code_tokens(title)
    if not codes:
        return None
    if brand in ("samsung",):
        for code in codes:
            if series := _tv_series(code):
                return series
    code = max(codes, key=len)                                # otherwise the longest code is the model
    line = _line_word(title, code)
    return f"{line} {code}" if line else code


# Words that may sit before a model code without being part of the product's name.
_NOT_A_LINE = frozenset((
    "tv", "led", "uhd", "fhd", "smart", "series", "model", "inch", "wireless", "headphones", "headphone", "earbuds",
    "earphones", "fryer", "airfryer", "manual", "digital", "new", "original", "black", "white", "blue", "grey", "gray",
    "silver", "red", "gold", "gaming", "laptop", "notebook", "phone", "mobile", "hdr", "google", "android", "qled",
    "oled", "crystal", "class", "edition", "oven", "microwave", "blender", "fridge", "refrigerator", "freezer",
    "washer", "machine", "dryer", "cooker", "kettle", "speaker", "soundbar", "monitor", "tablet", "the", "and", "with",
))


def _line_word(title: str, code: str) -> Optional[str]:
    """The product-line word right before a model code ("Tune" in "JBL Tune 780NC"), because the same
    number can belong to different products ("JBL Live 780NC"). Brands and generic words do not count."""
    words = re.split(r"[\s,;:()\[\]|]+", title)
    for i, word in enumerate(words):
        if word.upper().replace("-", "").replace("/", "") == code and i > 0:
            previous = re.sub(r"[^A-Za-z]", "", words[i - 1]).lower()
            if (len(previous) >= 3 and words[i - 1].isalpha() and previous not in _NOT_A_LINE
                    and previous not in BRANDS):
                return previous
            return None
    return None


def brand_of(title: str) -> Optional[str]:
    """The brand a title names (lower case), or None. Known even when the model is not."""
    lower = title.lower()
    if "iphone" in lower:
        return "apple"
    match = _BRAND_RE.search(lower)
    return match.group(1) if match else None


def condition_of(title: str) -> str:
    return "refurbished" if _REFURB_RE.search(title) else "new"


def parse(title: str) -> Optional[ProductKey]:
    """The product a title describes, or None when it cannot be pinned down."""
    lower = title.lower()
    brand = brand_of(title)
    if not brand:
        return None
    model = model_of(title, brand)
    if not model:
        return None
    is_phone = model.startswith(("iphone", "galaxy"))
    if is_phone:
        variant = _storage(title) or ""
        if not variant:
            return None                                       # 'iPhone 13' without storage: which one?
        if brand != "apple":
            # 4G and 5G versions of one model are different phones; a title naming both says nothing.
            networks = set(re.findall(r"(?<![a-z0-9])([45])g(?![a-z0-9])", lower))
            if len(networks) == 1:
                variant += f" {networks.pop()}g"
    else:
        size = _size(title)
        variant = f"{size}in" if size else ""
    return ProductKey(brand=brand, model=model, variant=variant, condition=condition_of(title))


@dataclass
class ProductGroup:
    """One product with every store's listing of it. A listing that could not be identified is a group of one."""
    id: str
    key: Optional[ProductKey]
    members: list                    # listings, in-stock first, cheapest first

    @property
    def title(self) -> str:
        return " ".join(min((m.title for m in self.members), key=len).split())   # the cleanest (shortest) store title

    @property
    def image_url(self) -> Optional[str]:
        return next((m.image_url for m in self.members if m.image_url), None)

    @property
    def brand(self) -> Optional[str]:
        return self.key.brand if self.key else next(filter(None, (brand_of(m.title) for m in self.members)), None)

    @property
    def condition(self) -> str:
        return self.key.condition if self.key else condition_of(self.members[0].title)

    @property
    def stores(self) -> list[str]:
        return sorted({m.store for m in self.members})

    @property
    def best(self):
        """The cheapest listing that can be bought (or the cheapest at all, if everything is sold out)."""
        return self.members[0]


def group_listings(listings: list) -> list[ProductGroup]:
    """Merge listings that are the same product (see the module note); order groups cheapest-first.

    Works on anything with .id, .title, .price, .in_stock, .image_url and .store."""
    by_key: dict[ProductKey, list] = {}
    groups: list[ProductGroup] = []
    for listing in listings:
        key = parse(listing.title)
        if key is None:
            groups.append(ProductGroup(id=f"listing-{listing.id}", key=None, members=[listing]))
        elif key in by_key:
            by_key[key].append(listing)
        else:
            by_key[key] = [listing]
            groups.append(ProductGroup(id=str(key).replace(" | ", "-").replace(" ", "-").lower(), key=key, members=by_key[key]))
    for group in groups:
        group.members.sort(key=lambda m: (not m.in_stock, m.price))
    groups.sort(key=lambda g: (not g.best.in_stock, g.best.price))
    return groups
