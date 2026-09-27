# Архитектура Buyer CRM

## Слои

```
Telegram bot ─┐
Mini App API ─┤  (Phase 6–7)
Dashboard API ┤  (Phase 8)          ┌────────────┐     ┌──────────────┐     ┌─────────────┐
AI assistant ─┘  (Phase 9)  ──────▶ │  services  │ ──▶ │ repositories │ ──▶ │   storage   │ ──▶ Firestore
                                    └────────────┘     └──────────────┘     └─────────────┘
                                     бизнес-правила      маппинг              Database-порт:
                                     роли, транзакции    документ ↔ модель    Firestore | InMemory
```

| Пакет | Что внутри | Что запрещено |
|---|---|---|
| `crm/domain` | статусы, ID, деньги, модели, правила видимости (`views.py`) | импорт Firestore и Telegram |
| `crm/storage` | порт `Database`/`Transaction`, `FirestoreDatabase`, `InMemoryDatabase` | бизнес-логика |
| `crm/repositories` | имена коллекций, чтение/запись конкретных документов | решения о деньгах и статусах |
| `crm/services` | все операции CRM: `OrderService`, `ShipmentService`, `FinanceService`, `BalanceLedger`, `RoleResolver` | Telegram-специфика |
| `crm/bot` | aiogram: middleware ролей, парсинг аргументов, тексты ответов, тонкие хендлеры | прямой доступ к Firestore |

Хендлер: разобрать аргументы → `await asyncio.to_thread(service.method, actor, …)` → отформатировать ответ.
Firestore-клиент синхронный, поэтому сервисы вызываются в отдельном потоке и не блокируют event loop.

Mini App, веб-панель и AI-ассистент будут вызывать **те же сервисы**. Например, форма
«Создать отправку» вызовет тот же `ShipmentService.ship_orders`, что и `/cargo`.

## Модель данных Firestore

Существующие документы не мигрируются. Код только добавляет новые поля и никогда
не перезаписывает документ целиком (`update`, а не `set`), поэтому чужие поля сохраняются.

### `orders/{nN}`

| Поле | Кто пишет | Смысл |
|---|---|---|
| `order_id`, `status`, `purchase_price`, `client_price`, `profit`, `cargo_code` | было | как раньше; `profit = client_price − purchase_price` |
| `charged_amount_krw` | **новое** | сколько по заказу сейчас списано с баланса. `/buy` ставит `client_price`, `/cancel` ставит 0 |
| `refunded_amount_krw` | новое | сколько вернул `/cancel` |
| `shipment_id` | новое | ID отправки |
| `bought_at`, `warehouse_at`, `cargo_at`, `delivered_at`, `cancelled_at`, `created_at`, `updated_at` | новое | UTC Timestamp |
| `created_by`, `updated_by` | новое | `tg:<telegram id>` |
| `brand`, `model`, `size`, `photo_url`, `thumbnail_url`, `source_url`, `source_chat_id`, `source_message_id`, `client_comment`, `internal_comment`, `attention_required` | новое, по мере фаз | см. ТЗ |

### `shipments/{SHP-YYYY-NNN}`
`shipment_id`, `shipment_number` (сквозной номер «Отправка #18»), `tracking_code`, `box_number`,
`weight_kg`, `shipping_cost_krw`, `shipment_date`, `photo_url`, `order_ids[]`, `comment`,
`created_at/by`, `updated_at/by`. Год в ID берётся по времени Сеула.

### `transactions/{id}`: ledger баланса (только добавление)
`transaction_id`, `type` (`order_charge` | `order_refund` | `deposit` | `adjustment` | `shipping_charge`),
`amount_krw` (со знаком), `balance_before`, `balance_after`, `order_id`, `shipment_id`, `comment`,
`created_at`, `created_by`, `source`.

ID детерминированные там, где это даёт идемпотентность:
`order_charge_n5`, `order_refund_n5`, `deposit_tg<chat>_<message>`, `adjustment_tg<chat>_<message>`.

### Прочее
* `client_info/main_client`: `telegram_id`, `name`, `balance` (KRW, может быть < 0). Добавляется `balance_updated_at`.
* `settings/general`: `krw_per_usd`, `updated_at`, `updated_by`.
* `counters/orders.next_id`, `counters/shipments.next_id`: создаются автоматически при первом использовании
  (для заказов `next_id = max(nN) + 1`, т. е. `n126`).
* `audit_logs/{id}`: `actor`, `source`, `action`, `entity_type`, `entity_id`, `before`, `after`, `timestamp`.

## Финансовые инварианты

1. **Баланс меняет только `BalanceLedger.apply`.** Он пишет новый баланс и запись в `transactions`
   в той же транзакции, поэтому `balance = начальный баланс + Σ amount_krw` всегда.
2. **`/buy` списывает один раз.** Внутри одной транзакции проверяется статус заказа и `charged_amount_krw`:
   * `new` и ничего не списано → списание;
   * уже выкуплен с теми же ценами → «уже выкуплен», ничего не меняется;
   * уже выкуплен с другими ценами → отказ (изменение цены станет отдельной операцией);
   * вторая линия защиты: запись `order_charge_nN` создаётся через `create`, и второе списание
     физически невозможно, даже если статус заказа сбросить вручную в консоли.
3. **`/cancel` возвращает ровно `charged_amount_krw` и обнуляет его**, поэтому повторный `/cancel` возвращает 0.
4. **Нет частичных операций.** Заказ, баланс, ledger и audit пишутся одним commit;
   при конфликте с параллельной операцией транзакция целиком повторяется на свежих данных.
   Это проверено тестами с параллельными потоками на Firestore Emulator.
5. **Статусы, которые двигают деньги, ставятся только своими командами.** `/status` не умеет
   `bought`/`cancelled`/`new`.
6. Пополнение и корректировка из Telegram идемпотентны по ID сообщения: повторная доставка того же апдейта не зачислит деньги дважды.

## Совместимость с существующими данными

Старый `/buy` не хранил, сколько списано. Поэтому для документов без `charged_amount_krw` действует правило:

> статус `bought`/`warehouse`/`cargo`/`delivered` ⇒ `client_price` был списан; `new`/`cancelled` ⇒ списаний нет.

При первой записи в такой заказ вычисленное значение сохраняется в `charged_amount_krw` явно.
Заказ с нераспознанным статусом блокируется для финансовых операций (понятная ошибка, данные не трогаются).

Перед первым запуском выполните `python -m crm.tools.doctor`. Утилита только читает базу
и показывает, соответствуют ли реальные документы этим допущениям: типы полей, неизвестные статусы,
выкупленные заказы без цены, состояние счётчиков.

## Решения, принятые по умолчанию (безопасные)

| Ситуация | Поведение сейчас |
|---|---|
| `/buy` уже выкупленного заказа с другой ценой | отказ, баланс не меняется |
| `/buy` отменённого заказа | отказ |
| `/cancel` заказа в статусе `cargo`/`delivered` или внутри отправки | отказ; возврат, если нужен, через `/adjust` с комментарием |
| `/status warehouse/delivered` для заказа в статусе `new` | пропуск: сначала `/buy` |
| `/status cargo` без отправки | пропуск: используйте `/cargo` (он создаёт shipment) |
| `/cargo` с трек-номером, который уже есть | заказы добавляются в существующую отправку, повтор команды ничего не меняет |
| `/cargo` для заказа из другой отправки | пропуск с причиной (перенос между отправками появится позже) |
| Стоимость доставки в shipment | только хранится, **с баланса не списывается** |
| Ответы бота в группе | всегда с клиентской видимостью: закупка, прибыль и `internal_comment` показываются только в личке админа |
| Трек-номер | приводится к верхнему регистру: латиница, цифры, дефис |
| Лимиты | ≤ 100 заказов за команду; ≤ ₩1 000 000 000 за операцию; курс 100–10 000 |

## Открытые вопросы (нужно решение владельца)

Эти пункты меняют финансовую логику, поэтому я не решал их молча:

1. **Доставка.** Списывать ли `shipping_cost_krw` с баланса клиента (тип `shipping_charge`)? Если да, то в момент создания отправки или отдельной командой?
2. **Изменение цены после выкупа.** Нужна ли команда вида `/price 5 180000`, которая меняет `client_price` и проводит разницу через ledger (`adjustment` на ±Δ)?
3. **Отмена отправленного заказа.** Нужен ли возврат для `cargo`/`delivered` (брак, возврат продавцу), или достаточно `/adjust`?
4. **Legacy-правило выше.** Верно ли, что старый `/buy` всегда списывал `client_price`, а старые отменённые заказы уже возвращены (или не списывались)?
5. **Начальный баланс.** История ledger начинается с момента запуска: `balance_before` первой записи равен текущему балансу. Нужна ли явная запись «Начальный баланс»?
6. **Комментарии корректировок видит клиент** (в истории баланса). Нужен ли отдельный внутренний комментарий для `/adjust`?

## Roadmap

| Фаза | Статус |
|---|---|
| 1. Foundation: структура, service layer, репозитории, конфиг, Firebase init, ошибки | ✅ |
| 2. Order backend: `/buy`, `/cancel`, `/status`, `/cargo`, идемпотентность, транзакции, счётчик | ✅ |
| 4. Finance (backend): ledger, баланс KRW/USD, пополнения, корректировки, курс | ✅ backend и команды бота |
| 5. Shipments (backend): коллекция, создание/дополнение, детали | ✅ backend; фото отправки — с Phase 3 |
| 10. Hardening (частично): audit log, deny-all Security Rules, тесты на эмуляторе, CI | ✅ частично |
| 3. Image pipeline + Gemini parser + draft orders из группы | следующий этап |
| 6–8. Mini App (client/admin), desktop dashboard | далее |
| 9. AI assistant (intent → validator → allowed action → service) | далее |
