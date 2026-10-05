import pytest

from beismart.parsing import is_relevant, parse_price


@pytest.mark.parametrize("text,expected", [
    ("KSh 28,999", 28999.0),
    ("KSh\n 399,999.00", 399999.0),
    ("KES 55.00", 55.0),
    ("KSh 507 - KSh 508", 507.0),
    ("Current price is: KSh399,999.00.", 399999.0),
    ("", None),
    (None, None),
    ("Out of stock", None),
    ("KSh 0", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_matches_when_all_words_present():
    assert is_relevant("Samsung 43 Inch Smart TV", "samsung tv")


def test_two_letter_words_count():
    assert not is_relevant("Samsung Soundbar", "samsung tv")


def test_accessories_dropped_for_a_product_search():
    assert not is_relevant("Samsung TV Wall Mount Bracket", "samsung tv")
    assert not is_relevant("Samsung Galaxy A36 Silicone Case", "samsung galaxy a36")


def test_accessories_kept_when_searched_for():
    assert is_relevant("Samsung Galaxy A36 Silicone Case", "galaxy a36 case")


def test_accessory_words_match_whole_words_only():
    # 'band' / 'case' inside other words must not trigger the filter
    assert is_relevant("Samsung Showcase Brand TV", "samsung tv")


def test_plural_search_matches_singular_titles():
    assert is_relevant("P47 Bluetooth Headphone, Wireless", "headphones")
    assert is_relevant("Refurbished Laptop, 10th Generation Core i5", "laptops")


def test_category_names_are_not_used_to_drop_products():
    # Jumia files headphones under 'Accessories & Supplies'; the title decides, not the category.
    assert is_relevant("M48PRO Bluetooth Headphones Ultra-Long Battery Life", "headphones")
