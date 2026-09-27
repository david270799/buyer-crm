from crm.config import load_settings
from crm.storage.memory import InMemoryDatabase
from crm.tools import doctor


def test_doctor_reads_hand_made_data_without_writing(capsys):
    db = InMemoryDatabase()
    db.seed("client_info", "main_client", {"telegram_id": 2002, "name": "C", "balance": 1500.0})
    db.seed(
        "orders",
        "n1",
        {"order_id": 1, "status": "bought", "client_price": 100, "purchase_price": 80.0},
    )
    db.seed("orders", "n125", {"order_id": "n125", "status": "в пути"})
    db.seed("orders", "n7", {"status": "warehouse"})
    commits = db.commit_count

    report = doctor.run(db, load_settings({"BOT_TOKEN": "123:abcd", "ADMIN_TELEGRAM_IDS": "1"}))

    out = capsys.readouterr().out
    assert db.commit_count == commits
    assert report.problems == 0
    assert "максимальный номер: n125" in out
    assert "нераспознанный статус у 1 заказов" in out and "n125" in out
    assert "списание не записано" in out and "n7" in out
    assert "next_id = 126" in out
    assert "…abcd" in out and "123:abcd" not in out


def test_doctor_reports_missing_client(capsys):
    report = doctor.run(InMemoryDatabase(), load_settings({}, require_bot=False))
    assert report.problems >= 1
    assert "документ не найден" in capsys.readouterr().out
