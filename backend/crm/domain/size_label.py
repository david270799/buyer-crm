def size_text(size: str | None, size_kr: str | None) -> str | None:
    """«L · KR 80», «KR 270», «42» — the usual and the Korean size together."""
    parts = [size, f"KR {size_kr}" if size_kr else None]
    return " · ".join(p for p in parts if p) or None
