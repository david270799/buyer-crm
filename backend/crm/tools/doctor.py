"""Read-only health check of configuration and existing Firestore data.

    python -m crm.tools.doctor

It never writes. Run it before the first start against the real project and
after adding documents by hand in the Firebase console: it shows documents
the CRM cannot interpret (unknown status, charges that were never recorded).
"""

import sys
from collections import Counter

from dotenv import find_dotenv, load_dotenv

from crm.config import Settings, load_settings
from crm.domain.enums import CHARGED_STATUSES
from crm.domain.errors import ConfigurationError
from crm.domain.ids import order_number
from crm.domain.models import ClientInfo, GeneralSettings, Order
from crm.storage import Database


class Report:
    def __init__(self) -> None:
        self.problems = 0
        self.warnings = 0

    def ok(self, text: str) -> None:
        print(f"  ✅ {text}")

    def info(self, text: str) -> None:
        print(f"  ·  {text}")

    def warn(self, text: str) -> None:
        self.warnings += 1
        print(f"  ⚠️  {text}")

    def fail(self, text: str) -> None:
        self.problems += 1
        print(f"  ❌ {text}")


def check_config(settings: Settings, report: Report) -> None:
    print("Конфигурация")
    if settings.bot_token:
        report.ok(f"BOT_TOKEN задан (…{settings.bot_token[-4:]})")
    else:
        report.fail("BOT_TOKEN не задан")
    if settings.admin_ids:
        report.ok(f"ADMIN_TELEGRAM_IDS: {sorted(settings.admin_ids)}")
    else:
        report.fail("ADMIN_TELEGRAM_IDS не задан")
    if settings.firebase_storage_bucket:
        report.ok(f"FIREBASE_STORAGE_BUCKET: {settings.firebase_storage_bucket}")
    else:
        report.warn("FIREBASE_STORAGE_BUCKET не задан — фото заказов не сохраняются")
    if not settings.gemini_api_key:
        report.warn("GEMINI_API_KEY не задан — заказы по фото без распознавания модели")
    if settings.allowed_chat_ids:
        report.info(f"ALLOWED_CHAT_IDS: {sorted(settings.allowed_chat_ids)}")
    else:
        report.info(
            "ALLOWED_CHAT_IDS не задан — бот отвечает в любом чате (админ-команды всё "
            "равно только от админа)"
        )


def check_client(db: Database, settings: Settings, report: Report) -> None:
    print("client_info/main_client")
    raw = db.get("client_info", "main_client")
    if raw is None:
        report.fail(
            "документ не найден — добавьте бота в группу и ответьте /setclient "
            "на сообщение клиента (или /setclient <ID>)"
        )
        return
    client = ClientInfo.from_doc("main_client", raw)
    if client.telegram_id is None:
        report.fail(f"telegram_id отсутствует или не число: {raw.get('telegram_id')!r}")
    else:
        report.ok(f"telegram_id = {client.telegram_id} ({type(raw['telegram_id']).__name__})")
        if client.telegram_id in settings.admin_ids:
            report.warn("telegram_id клиента совпадает с ID администратора")
    if client.balance is None:
        report.fail(f"balance отсутствует или не число: {raw.get('balance')!r}")
    else:
        kind = type(raw["balance"]).__name__
        report.ok(f"balance = {client.balance:,} KRW ({kind})")
        if kind != "int":
            report.warn("balance хранится не целым числом; новый код будет записывать int")


def check_orders(db: Database, report: Report) -> int:
    print("orders")
    rows = db.query("orders")
    report.info(f"документов: {len(rows)}")
    numbers, statuses, id_field_types = [], Counter(), Counter()
    unknown, non_canonical, bought_without_charge, float_prices = [], [], [], []
    for doc_id, data in rows:
        number = order_number(doc_id)
        if number is None:
            non_canonical.append(doc_id)
        else:
            numbers.append(number)
        statuses[repr(data.get("status"))] += 1
        id_field_types[type(data.get("order_id")).__name__] += 1
        order = Order.from_doc(doc_id, data)
        if order.status is None:
            unknown.append(doc_id)
        if order.status in CHARGED_STATUSES and not order.is_charged:
            bought_without_charge.append(doc_id)
        if any(isinstance(data.get(f), float) for f in ("purchase_price", "client_price")):
            float_prices.append(doc_id)

    max_number = max(numbers, default=0)
    report.info(f"максимальный номер: N{max_number}" if numbers else "заказов N… нет")
    report.info("статусы: " + ", ".join(f"{k}: {v}" for k, v in statuses.most_common()))
    report.info("тип поля order_id: " + ", ".join(f"{k}: {v}" for k, v in id_field_types.items()))
    if unknown:
        report.warn(
            f"нераспознанный статус у {len(unknown)} заказов (операции с ними будут "
            f"остановлены): {', '.join(unknown[:15])}"
        )
    else:
        report.ok("все статусы распознаны")
    if non_canonical:
        report.warn(f"документы с ID не формата N…: {', '.join(non_canonical[:15])}")
    if bought_without_charge:
        report.warn(
            "статус «выкуплен» и дальше, но списание не записано (заказ добавлен не через CRM): "
            "отмена ничего не вернёт, /buy откажет — " + ", ".join(bought_without_charge[:15])
        )
    if float_prices:
        report.info(f"цены дробным числом у {len(float_prices)} заказов (читаются корректно)")
    return max_number


def check_counters(db: Database, max_order: int, report: Report) -> None:
    print("counters")
    orders_counter = db.get("counters", "orders")
    if orders_counter is None:
        report.info(
            f"counters/orders нет — будет создан при первом заказе с next_id = {max_order + 1}"
        )
    elif orders_counter.get("next_id", 0) <= max_order:
        report.warn(
            f"counters/orders.next_id = {orders_counter.get('next_id')} ≤ N{max_order}; "
            "занятые номера будут пропущены автоматически"
        )
    else:
        report.ok(f"counters/orders.next_id = {orders_counter['next_id']}")
    shipments = db.get("counters", "shipments")
    report.info(
        f"counters/shipments.next_id = {shipments.get('next_id')}"
        if shipments
        else "counters/shipments нет — будет создан при первой отправке"
    )


def check_settings(db: Database, report: Report) -> None:
    print("settings/general")
    settings = GeneralSettings.from_doc(db.get("settings", "general"))
    if settings.krw_per_usd is None:
        report.warn("курс krw_per_usd не задан — баланс в USD не показывается (/rate 1350)")
    else:
        report.ok(f"krw_per_usd = {settings.krw_per_usd}")


def check_gemini(settings: Settings, report: Report) -> None:
    from crm.services.recognition import RecognitionError, create_recognizer

    recognizer = create_recognizer(settings.gemini_api_key, settings.gemini_model)
    if recognizer is None:
        return
    print("Gemini")
    try:
        recognizer.check()
    except RecognitionError as exc:
        report.fail(f"{recognizer.engine}: {exc}")
    else:
        report.ok(f"ключ подходит, модель {recognizer.engine} доступна")


def run(db: Database, settings: Settings, *, live: bool = False) -> Report:
    """`live` also calls external services (Gemini) to check the keys."""
    report = Report()
    check_config(settings, report)
    if live:
        check_gemini(settings, report)
    check_client(db, settings, report)
    max_order = check_orders(db, report)
    check_counters(db, max_order, report)
    check_settings(db, report)
    print(f"\nИтого: ошибок {report.problems}, предупреждений {report.warnings}")
    return report


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    try:
        settings = load_settings(require_bot=False)
        from crm.firebase import create_database

        db = create_database(settings)
        report = run(db, settings, live=True)
    except ConfigurationError as exc:
        print(f"❌ {exc.user_message}", file=sys.stderr)
        sys.exit(2)
    sys.exit(1 if report.problems else 0)


if __name__ == "__main__":
    main()
