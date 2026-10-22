import pytest

from crm.services.sizes import order_sizes, split_sizes


@pytest.mark.parametrize(
    "text, expected",
    [
        ("L 80", ("L", "80")),
        ("L/80", ("L", "80")),
        ("m-95", ("M", "95")),
        ("XL 105", ("XL", "105")),
        ("42/265", ("42", "265")),
        ("42 - 265", ("42", "265")),
        ("270", (None, "270")),
        ("42", ("42", None)),
        ("S", ("S", None)),
        ("100", (None, "100")),
        ("US 9", ("US 9", None)),
        ("KR 265", (None, "265")),
        ("42.5 / 270", ("42.5", "270")),
        ("https://m.dk-on.com/UMBRO/product/UR423CFPO2/DVY0\n\nL 80", ("L", "80")),
        ("42 или 43", (None, None)),  # unsure: two usual sizes
        ("", (None, None)),
    ],
)
def test_split_sizes(text, expected):
    assert split_sizes(text) == expected


def test_caption_wins_then_gemini():
    assert order_sizes("L", "L 80", from_caption=True) == ("L", "80")
    assert order_sizes("270", "срочно", from_caption=True) == (None, "270")
    assert order_sizes("27cm", None, from_caption=True) == ("27cm", None)  # cannot place
    # several links: the size is per link, the caption is not used
    assert order_sizes("M", "M 95\\nL 100", from_caption=False) == ("M", None)
