from crm.services.order_split import plan, quantity, strip_quantity
from crm.services.recognition import Recognition

R = Recognition(brand="Nike", model="Dunk", size="42")


def test_quantity_marker():
    assert quantity("42 3ta") == 3
    assert quantity("3 TA, 270") == 3
    assert quantity("2та") == 2
    assert quantity("Data 270") == 1  # "ta" inside a word is not a marker
    assert quantity("42 99ta") == 10  # capped
    assert strip_quantity("42 3ta") == "42"


def test_plan_copies_and_links():
    assert len(plan("42 3ta", R)) == 3
    assert plan("42", R)[0].brand == "Nike"
    items = plan("M https://a.kr/1\nL https://b.kr/2", R)
    assert [(i.link, i.size, i.brand) for i in items] == [
        ("https://a.kr/1", "M", None),
        ("https://b.kr/2", "L", None),
    ]
    # Sizes listed in the same order as the links.
    items = plan("https://a.kr/1 https://b.kr/2 M 100", R)
    assert [i.size for i in items] == ["M", "100"]
    # One size for two links is ambiguous: none.
    assert [i.size for i in plan("https://a.kr/1 https://b.kr/2 M", R)] == [None, None]
