"""Settings helpers."""


def test_http_client_logs_never_show_request_addresses():
    """Security audit (10.11.2026): httpx at INFO printed
    «POST https://api.telegram.org/bot<token>/sendPhoto» into the server log."""
    import logging

    from crm.config import apply_log_level

    apply_log_level("DEBUG")
    try:
        assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("httpcore").getEffectiveLevel() == logging.WARNING
    finally:
        logging.getLogger().setLevel(logging.WARNING)
