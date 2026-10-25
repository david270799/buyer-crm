import pytest

from crm.bot import formatting as fmt
from crm.domain.errors import PermissionDeniedError
from crm.services.server_status import ServerStatus, parse_meminfo, parse_rss_mb, read_status

MEMINFO = """MemTotal:        4194304 kB
MemFree:         3500000 kB
MemAvailable:    3565158 kB
Buffers:               0 kB
"""


def test_parse_meminfo_and_rss():
    assert parse_meminfo(MEMINFO) == (4096, 3481)
    assert parse_meminfo("") == (None, None)
    assert parse_rss_mb("Name:\tpython\nVmRSS:\t  184320 kB\n") == 180
    assert parse_rss_mb("Name:\tpython\n") is None


def test_server_status_text_says_what_fits():
    status = ServerStatus(
        cpus=8,
        load=(0.12, 0.1, 0.05),
        mem_total_mb=4096,
        mem_available_mb=3481,
        disk_total_gb=105.0,
        disk_free_gb=99.7,
        crm_mb=180,
        uptime_s=3 * 86400 + 4 * 3600,
    )
    text = fmt.server_status(status)
    assert "8 потоков · почти не загружен" in text
    assert "занято 0.6 ГБ из 4.0 ГБ (15 %)" in text
    assert "свободно 99.7 ГБ" in text and "CRM сама занимает: 180 МБ" in text
    assert "3 дн. 4 ч" in text
    assert "<b>19</b> небольших" in text  # (3481 - 500) // 150


def test_read_status_is_admin_only(admin, client_actor, tmp_path):
    with pytest.raises(PermissionDeniedError):
        read_status(client_actor, tmp_path)
    status = read_status(admin, tmp_path)
    assert status.cpus >= 1 and status.disk_total_gb > 0
