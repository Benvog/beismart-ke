from dataclasses import dataclass
from typing import Optional

import pytest

from beismart.products import ProductKey, brand_of, condition_of, group_listings, parse


def key(title):
    return parse(title)


# ── the same product, written differently by different stores ────────────────

@pytest.mark.parametrize("a,b", [
    ("Samsung 32H5000 32\" Inch Smart TV Full HD", "Samsung 32-Inch Class HD H5000F Smart TV (2025 Model)"),
    ("Samsung 32 Inch 32H5000 Smart Tv", "Samsung 32\" LED TV HD Ready, Smart, UA32H5000FUXKE"),
    ("Samsung 43\" LED UHD TV - 4K, Smart, UA43U8000FUXKE", "Samsung 43 Inch Crystal UHD U8000F 4K Smart TV (2025 Model)"),
    ("Samsung 43F6000FU 43\" Inch Television Smart FHD TV", "Samsung 43 Inch F6000F Smart Full HD LED TV"),
    ("Apple iPhone 13 128GB ROM 4GB RAM 6.1\"", "Apple iphone 13 128gb"),
    ("iPhone 15 ProMax 256GB Titanium", "Apple iPhone 15 Pro Max 256GB"),
    ("VON Manual Air Fryer, 6.5L VAF065MCK", "Von Air Fryer Vaf065Mck 6.5L Manual Book"),
    ("JBL Tune 780NC Wireless Headphones", "JBL TUNE 780NC WIRELESS OVER-EAR NOISE CANCELLING HEADPHONES, BLUE"),
    ("Samsung Galaxy A16 128GB+4GB 6.7\" Super AMOLED", "Samsung Galaxy A16, 4GB RAM + 128GB ROM 6.7\""),
])
def test_same_product_gets_the_same_key(a, b):
    assert key(a) is not None and key(a) == key(b)


# ── different products must never be merged ─────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("Samsung 43\" LED UHD TV UA43U8000FUXKE", "Samsung 50\" LED UHD TV UA50U8000FUXKE"),           # size
    ("Apple iPhone 13 128GB", "Apple iPhone 13 256GB"),                                             # storage
    ("Apple iPhone 13 128GB", "Apple iPhone 13 Pro 128GB"),                                         # model
    ("Apple iPhone 13 Pro 256GB", "Apple iPhone 13 Pro Max 256GB"),
    ("Apple iPhone 13 128GB", "Refurbished Apple iPhone 13 128GB"),                                 # condition
    ("Apple iPhone 13 Pro Max 128gb dual sim bh93%", "Apple iPhone 13 Pro Max 128GB New"),          # used (battery health)
    ("Samsung Galaxy A07 64GB", "Samsung Galaxy A07s 64GB"),                                        # model suffix
    ("Samsung Galaxy A17 4G 128GB", "Samsung Galaxy A17 5G 128GB"),                                 # network
    ("JBL Tune 780NC Wireless Headphones", "JBL Live 780NC Wireless Over Ear Headphones"),          # product line
    ("Samsung Galaxy S24 128GB", "Samsung Galaxy S24 Ultra 128GB"),
])
def test_different_products_get_different_keys(a, b):
    assert key(a) != key(b)


# ── when unsure, do not group ───────────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "Apple iPhone 13",                                   # which storage?
    "SAMSUNG 43\" inch SMART TV Full HD Television Netflix YouTube",   # no model code
    "Generic Bluetooth Headphones Wireless",             # no brand, no model
    "Tecno Spark 10 ROM+8GB 128GB 6.6 in",               # a spec fragment is not a model
])
def test_unclear_titles_have_no_key(title):
    assert key(title) is None


def test_the_key_names_the_four_facts():
    k = key("Refurbished Apple iPhone 13 128GB")
    assert k == ProductKey(brand="apple", model="iphone 13", variant="128gb", condition="refurbished")


# ── building groups ─────────────────────────────────────────────────────────

@dataclass
class L:
    id: int
    store: str
    title: str
    price: float
    in_stock: bool = True
    image_url: Optional[str] = None


def test_listings_of_one_product_become_one_group_cheapest_first():
    groups = group_listings([
        L(1, "Jumia", "Samsung 32H5000 32\" Inch Smart TV", 21386.0),
        L(2, "Amazon", "Samsung 32-Inch Class HD H5000F Smart TV (2025 Model)", 19089.0),
        L(3, "Hotpoint", "Samsung 32\" LED TV UA32H5000FUXKE", 22990.0),
    ])
    assert len(groups) == 1
    assert [m.store for m in groups[0].members] == ["Amazon", "Jumia", "Hotpoint"]
    assert groups[0].best.price == 19089.0
    assert groups[0].stores == ["Amazon", "Hotpoint", "Jumia"]


def test_an_unidentified_listing_is_a_group_of_one():
    groups = group_listings([L(1, "Kilimall", "SAMSUNG 43\" inch SMART TV Full HD", 33695.0)])
    assert len(groups) == 1 and groups[0].key is None and groups[0].id == "listing-1"


def test_groups_are_ordered_cheapest_first_with_sold_out_last():
    groups = group_listings([
        L(1, "A", "Apple iPhone 13 128GB", 50000.0),
        L(2, "B", "Samsung Galaxy A16 128GB", 18000.0),
        L(3, "C", "Samsung 32H5000 32\" Inch Smart TV", 9000.0, in_stock=False),
    ])
    assert [g.best.price for g in groups] == [18000.0, 50000.0, 9000.0]


def test_a_sold_out_listing_is_never_the_best_when_one_is_in_stock():
    g = group_listings([
        L(1, "A", "Apple iPhone 13 128GB", 40000.0, in_stock=False),
        L(2, "B", "Apple iPhone 13 128GB", 47500.0),
    ])[0]
    assert g.best.store == "B"


def test_the_group_title_is_the_cleanest_store_title_and_image_is_any_available():
    g = group_listings([
        L(1, "A", "Apple iPhone 13 128GB ROM 4GB RAM 6.1\" Super Retina XDR OLED Display 5G Speed", 32500.0),
        L(2, "B", "Apple iPhone 13 128gb", 47500.0, image_url="https://img/x.jpg"),
    ])[0]
    assert g.title == "Apple iPhone 13 128gb"
    assert g.image_url == "https://img/x.jpg"


def test_group_ids_are_stable():
    a = group_listings([L(1, "A", "Apple iPhone 13 128GB", 1.0)])[0].id
    b = group_listings([L(9, "B", "iphone 13 128gb new", 2.0)])[0].id
    assert a == b == "apple-iphone-13-128gb-new"


@pytest.mark.parametrize("title,brand", [
    ("Hisense 94L Single Door Fridge", "hisense"),
    ("Apple iPhone 15 128GB", "apple"),
    ("iPhone 13 Pro Max 256GB", "apple"),
    ("Russell Hobbs 4.5L Air Fryer", "russell hobbs"),
    ("Generic 5L Digital Air Fryer", None),
    ("LGA1700 motherboard", None),                    # a brand inside a longer word does not count
])
def test_brand_is_found_even_without_a_model(title, brand):
    assert brand_of(title) == brand


@pytest.mark.parametrize("title,condition", [
    ("Samsung Galaxy S23 Refurbished 256GB", "refurbished"),
    ("Ex-UK HP EliteBook 840 G5", "refurbished"),
    ("Samsung Galaxy S23 256GB", "new"),
])
def test_condition_from_the_title(title, condition):
    assert condition_of(title) == condition


def test_an_unidentified_group_still_knows_its_brand_and_condition():
    group = group_listings([L(1, "Jumia", "Hisense fridge, refurbished, great deal", 9000.0)])[0]
    assert group.key is None and group.brand == "hisense" and group.condition == "refurbished"
