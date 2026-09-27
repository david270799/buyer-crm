# Buyer CRM

CRM байера, который выкупает товары в Южной Корее для одного постоянного B2B-клиента.
Основная валюта — KRW, баланс дополнительно показывается в USD по курсу администратора.

Сейчас реализован backend (Python 3.11, aiogram 3, firebase-admin) и Telegram-бот:
учёт заказов, финансово безопасные `/buy` и `/cancel`, история баланса (ledger), отправки
(shipments), `/cargo`, audit log. Архитектура, модель данных, финансовые инварианты и открытые вопросы
описаны в [docs/architecture.md](docs/architecture.md).

```
backend/
  crm/domain/        статусы, ID, деньги, модели, правила видимости полей
  crm/storage/       порт Database + Firestore и in-memory реализации
  crm/repositories/  маппинг документов Firestore
  crm/services/      вся бизнес-логика (общая для бота, Mini App, веб-панели и AI)
  crm/bot/           Telegram-бот (тонкие хендлеры)
  crm/tools/doctor   read-only проверка конфигурации и данных
  tests/             тесты: in-memory + Firestore Emulator
firestore.rules      deny-all для клиентских SDK (backend работает через Admin SDK)
```

## Попробовать без риска: демо-режим

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
BOT_TOKEN=<токен тестового бота> ADMIN_TELEGRAM_IDS=<ваш Telegram ID> python -m crm.bot --demo
```

Бот работает на данных в памяти: клиент с балансом ₩5,000,000, курс 1350, заказы
`n121`–`n125` в разных статусах. **Firebase не используется**, после перезапуска всё начинается заново.
Для теста лучше создать отдельного бота в @BotFather. Чтобы проверить, что видит клиент,
укажите `DEMO_CLIENT_TELEGRAM_ID` — Telegram ID второго аккаунта.

Сценарий для проверки: `/balance` → `/order 121` → `/buy 121 150000 180000` → ещё раз тот же `/buy`
(денег не списывает) → `/history` → `/cargo DEMO123 123 124 125` → `/shipments` → `/cancel 121`
→ `/balance`.

## Запуск

1. **Токен бота**: @BotFather → `/newbot` (или `/token` для существующего бота).
2. **Сервисный аккаунт Firebase**: Firebase Console → Project settings → Service accounts →
   *Generate new private key*. JSON-файл храните **вне репозитория**.
3. **Настройки**: `cp .env.example .env` и заполните `BOT_TOKEN`, `ADMIN_TELEGRAM_IDS`,
   `FIREBASE_CREDENTIALS`, `FIREBASE_PROJECT_ID`. Свой Telegram ID подскажет бот по команде `/whoami`.
4. **Установка**:
   ```bash
   cd backend
   python3.11 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```
5. **Проверка данных** (ничего не пишет в базу):
   ```bash
   python -m crm.tools.doctor
   ```
   Утилита покажет баланс клиента, статусы существующих заказов, максимальный номер `nN`
   и всё, что не совпадает с ожиданиями кода.
6. **Запуск бота**:
   ```bash
   python -m crm.bot
   ```
   Одновременно должен работать **один** экземпляр бота с этим токеном: long polling не делится между процессами.
7. **Группа**: добавьте бота в группу с клиентом. Админу в этой группе нужно выключить
   «Анонимность» (Remain anonymous), иначе Telegram не передаёт боту его ID и команды не пройдут проверку роли.
   Чтобы ограничить бота одной группой, укажите `ALLOWED_CHAT_IDS` (ID группы покажет `/whoami` в группе).

> Команду `/buy` лучше отправлять боту **в личке**: её текст содержит закупочную цену.
> Ответы бота в группе и так никогда не показывают закупку, прибыль и внутренние комментарии.

## Команды

| Команда | Кто | Что делает |
|---|---|---|
| `/buy 5 140000 170000` | админ | выкуп: закупка, цена клиенту; списывает `client_price` с баланса **один раз** |
| `/cancel 5` | админ | отмена; возвращает списанное **один раз** |
| `/status warehouse 5 7 12` | админ | статус нескольких заказов (`warehouse`, `cargo`, `delivered`; есть русские синонимы) |
| `/cargo TRACK123 5 10 18` | админ | создаёт отправку (или дополняет отправку с этим треком), ставит статус «Отправлен» |
| `/deposit 5000000 перевод` | админ | пополнение баланса |
| `/adjust -15000 комиссия` | админ | корректировка баланса с обязательной причиной |
| `/rate 1350` | админ | курс KRW за 1 USD |
| `/order 5` | админ, клиент | карточка заказа (клиент не видит закупку, прибыль и внутренние комментарии) |
| `/balance`, `/history` | админ, клиент | баланс в ₩ и $, история баланса |
| `/shipments`, `/shipment SHP-2026-001` | админ, клиент | отправки |
| `/whoami`, `/help` | все | Telegram ID и список команд |

Номера заказов можно писать как `5`, `n5`, `N05`, `#5`. Суммы — как `170000` или `170,000`.

## Тесты

```bash
cd backend
python -m pytest -q                      # быстрые тесты на in-memory базе
```

Полный прогон на настоящем Firestore Emulator (нужны Java 21 и `npm i -g firebase-tools`):

```bash
firebase emulators:exec --only firestore --project demo-buyer-crm "cd backend && python -m pytest -q"
```

Каждый тест, работающий с хранилищем, выполняется дважды: на in-memory фейке и на эмуляторе.
Среди них есть параллельные `/buy`, `/cancel` и создание заказов из нескольких потоков,
которые проверяют, что деньги не списываются дважды. CI (`.github/workflows/tests.yml`) запускает lint и полный прогон на каждый push.

## Безопасность

* Секреты только в `.env` или в переменных окружения, `.gitignore` не пропускает `.env` и JSON-ключи.
  Если ключ когда-либо попадал в чат, репозиторий или скриншот, перевыпустите его (@BotFather `/revoke`,
  новый ключ сервисного аккаунта).
* Роли: админ — из `ADMIN_TELEGRAM_IDS` (переменная окружения), клиент — `client_info/main_client.telegram_id`.
  Роль проверяется дважды: фильтром бота и внутри сервиса.
* `firestore.rules` запрещает любой доступ из браузера и Mini App. Всё идёт через backend.
  Правила **ещё не применены** к вашему проекту. Применить: `firebase deploy --only firestore:rules`
  (проверьте, что к Firestore не обращается напрямую никакое другое приложение).
