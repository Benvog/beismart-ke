import pytest

from beismart.matching import junk_reason, typical_price


@pytest.mark.parametrize("title,query", [
    ("Disposable Air Fryer Liner Square 40pcs", "air fryer"),
    ("Gondol Microwave Container G583 1l", "microwave"),
    ("Washing Machine Cleaner Lavender 250Ml", "washing machine"),
    ("13-Piece Air Fryer Accessory Set Household", "air fryer"),
    ("Persil Machine Washing Powder 3Kg", "washing machine"),
    ("Refurbished Transform an iPhone X into an iPhone 13", "iphone 13"),
    ("Descaler for Coffee Machines 500ml", "coffee machine"),
    ("Replacement Water Filter Cartridge", "water dispenser"),
])
def test_known_junk_is_caught_by_its_words(title, query):
    assert junk_reason(title, 800.0, query, None) is not None


@pytest.mark.parametrize("title,query", [
    ("Samsung 43 Inch Smart TV", "samsung tv"),
    ("Hisense 85Q7Q QLED VIDAA Smart 4K TV", "tv"),
    ("Ninja Air Fryer 5.7L", "air fryer"),
    ("Apple iPhone 13 128GB", "iphone 13"),
    ("Philips Blender Matte Black", "philips blender"),      # 'mat' inside another word must not match
    ("Showcase Brand TV", "tv"),
])
def test_real_products_are_left_alone(title, query):
    assert junk_reason(title, 40000.0, query, 40000.0) is None


def test_the_search_can_ask_for_the_accessory_itself():
    assert junk_reason("Air Fryer Liner 40pcs", 600.0, "air fryer liner", None) is None
    assert junk_reason("Microwave Container", 300.0, "microwave container", None) is None


def test_a_price_far_below_the_rest_is_flagged():
    reason = junk_reason("Samsung Galaxy A36 5G", 995.0, "samsung galaxy a36", 40000.0)
    assert reason and "far below" in reason


def test_a_normal_discount_is_not_flagged():
    assert junk_reason("Samsung Galaxy A36 5G", 30000.0, "samsung galaxy a36", 40000.0) is None


def test_no_price_judgement_with_too_few_results():
    assert typical_price([1000.0, 2000.0, 3000.0, 4000.0]) is None
    assert typical_price([1000.0, 2000.0, 3000.0, 4000.0, 5000.0]) == 3000.0


def test_junk_words_only_match_whole_words():
    # 'rack' inside 'bracket' / 'track', 'liner' inside 'airliner': none of these are the junk words
    assert junk_reason("Samsung Soundbar with Tracking Sound", 30000.0, "soundbar", None) is None
    assert junk_reason("Wall Bracketed Display Stand TV", 30000.0, "tv", None) is None


def test_vacuum_cleaners_are_products_not_cleaning_supplies():
    assert junk_reason("Hisense Vacuum Cleaner 2000W", 9000.0, "vacuum", None) is None
    assert junk_reason("Robot Cleaner Smart Mop", 20000.0, "robot", None) is None


def test_a_replacement_warranty_is_not_a_replacement_part():
    assert junk_reason("Samsung A06 6.7 inch, 12 Months Replacement Warranty", 15000.0, "samsung a06", None) is None
    assert junk_reason("Replacement Voice Remote for Samsung Smart TV", 1400.0, "samsung tv", None) is not None


def test_cheap_but_real_products_are_not_hidden_by_price():
    # headphones really do run from ~KSh 350 to 40,000; the typical price was ~4,500
    assert junk_reason("P47 Bluetooth Headphone Wireless", 349.0, "headphones", 4500.0) is None
    assert junk_reason("Mystery thing", 150.0, "headphones", 4500.0) is not None


def test_a_product_with_cleaner_in_its_marketing_name_is_not_a_cleaning_product():
    title = "Compact USB Rechargeable Mini Portable Washing Machine with 4000mAh Battery, Compact Electric Cleaner"
    assert junk_reason(title, 4824.0, "washing machine", None) is None


def test_products_sold_with_free_extras_are_not_accessories():
    laptop = "{Free Laptop Bag & Mouse} Lenovo ThinkPad 11E, Non-Touch, Intel, 4 GB"
    tv = 'SAMSUNG 32" INCH Smart TV Full HD + FREE ACCESSORIES and Wall Bracket'
    assert junk_reason(laptop, 14500.0, "laptop", None) is None
    assert junk_reason(tv, 23495.0, "samsung tv", None) is None
