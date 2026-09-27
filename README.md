# Buyer CRM

CRM байера, который выкупает товары в Южной Корее для одного постоянного B2B-клиента.
Основная валюта — KRW, баланс дополнительно показывается в USD по курсу администратора.

**Что есть сейчас**

| Часть | Статус |
|---|---|
| Telegram-бот: команды админа и клиента | ✅ |
| Mini App для клиента (только просмотр) | ✅ |
| Mini App для администратора (на телефоне) и та же панель на компьютере | ✅ |
| HTTP API с проверкой Telegram-подписи | ✅ |
| Перезаказ, история заказа, колокольчик уведомлений (важные / все) | ✅ |
| Фото: сжатие в WebP + миниатюры, Firebase Storage | ✅ загрузка вручную |
| Приём заказов из группы (фото → черновик заказа, Gemini) | следующий этап |
| AI-ассистент | позже |

Деньги: `/buy` списывает один раз, `/cancel` возвращает один раз (после отправки — не отменяется),
перезаказ и изменение стоимости доставки двигают только разницу, каждое изменение баланса записано в историю.
Подробности — [docs/architecture.md](docs/architecture.md), запуск в работу — [docs/deploy.md](docs/deploy.md).

```
backend/          Python 3.11+: aiogram 3, FastAPI, firebase-admin
  crm/domain/       статусы, ID, деньги, модели, правила видимости полей для клиента
  crm/storage/      порт Database (Firestore и in-memory), хранилище файлов
  crm/services/     вся бизнес-логика — общая для бота, Mini App и будущего AI
  crm/api/          HTTP API для Mini App (проверка Telegram initData)
  crm/bot/          Telegram-бот (тонкие хендлеры)
  crm/server.py     один процесс: API + Mini App + бот
  crm/tools/doctor  read-only проверка конфигурации и данных Firebase
web/              Mini App: React + TypeScript + Vite
Dockerfile, docker-compose.yml   сервер с HTTPS (Caddy)
```

## Посмотреть прямо сейчас: демо в браузере

Нужны Python 3.11+ и Node.js 20+. Firebase и ключи **не нужны** — данные в памяти.

```bash
cd web && npm install && npm run build && cd ..
cd backend
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m crm.server --demo
```

Откройте http://localhost:8080 и выберите «Администратор» или «Клиент». В демо 9 заказов
в разных статусах, две отправки, пополнение, возврат и списания за доставку за последние три недели.
Можно выкупать, отменять, создавать отправки, пополнять баланс — после перезапуска всё начнётся заново.

Если в `.env` указать `BOT_TOKEN` **тестового** бота и `ADMIN_TELEGRAM_IDS`, в демо заработает и бот.

## Запуск в работу

Коротко (подробно — [docs/deploy.md](docs/deploy.md)):

1. Сервер с доменом и HTTPS (VPS + `docker compose`, или Google Cloud Run).
2. `.env` из `.env.example`: `BOT_TOKEN`, `ADMIN_TELEGRAM_IDS`, `MINI_APP_URL`, `FIREBASE_*`.
3. `docker compose run --rm crm python -m crm.tools.doctor` — проверка существующих данных.
4. `docker compose up -d --build` — бот сам добавит кнопку **«CRM»**, которая открывает Mini App.

Админу в группе с клиентом нужно выключить «Анонимность» (Remain anonymous) — иначе Telegram
не передаёт боту его ID.

## Команды бота

| Команда | Кто | Что делает |
|---|---|---|
| `/buy 5 140000 170000` | админ | выкуп: закупка, цена клиенту; списывает `client_price` **один раз** |
| `/cancel 5` | админ | отмена; возвращает списанное **один раз**; после отправки отмены нет |
| `/rebuy 5 150000 185000 [ссылка] [причина]` | админ | перезаказ в другом магазине: новая закупка и цена, с баланса — только разница; причину увидит клиент, ссылку — только вы |
| `/status warehouse 5 7 12` | админ | статус нескольких заказов (`warehouse`, `cargo`, `delivered`; есть русские синонимы) |
| `/cargo TRACK123 5 10 18` | админ | создаёт отправку (или дополняет отправку с этим треком), статус «Отправлен» |
| `/shipcost 18 95000` | админ | стоимость доставки отправки #18; списывается с баланса (при изменении — разница) |
| `/deposit 5000000 перевод` | админ | пополнение баланса |
| `/adjust -15000 комиссия` | админ | корректировка баланса с обязательной причиной |
| `/rate 1350` | админ | курс KRW за 1 USD |
| `/order 5` | админ, клиент | карточка заказа |
| `/balance`, `/history` | админ, клиент | баланс в ₩ и $, история |
| `/shipments`, `/shipment 18` | админ, клиент | отправки |
| `/whoami`, `/help` | все | Telegram ID и список команд |

Номера заказов: `5`, `n5`, `N05`, `#5`. Суммы: `170000` или `170,000`.
Клиент нигде не видит закупку, прибыль, ссылки на магазины и внутренние комментарии;
`/buy` всё же лучше отправлять в личку — сам текст команды содержит закупочную цену.

## Тесты

```bash
cd backend && python -m pytest -q            # быстрые тесты (in-memory)
cd web && npm run typecheck && npm test       # фронтенд
# полный прогон на настоящем Firestore Emulator (Java 21 + firebase-tools):
firebase emulators:exec --only firestore --project demo-buyer-crm "cd backend && python -m pytest -q"
```

Каждый тест с хранилищем выполняется дважды — на in-memory фейке и на эмуляторе Firestore,
включая параллельные `/buy`, `/cancel` и создание заказов. CI на каждый push: lint, тесты,
сборка Mini App, сборка Docker-образа и smoke-тест.

## Безопасность

* Ключи — только в `.env` / `secrets/` на сервере; `.gitignore` и `.dockerignore` их не пропускают.
* Mini App: сервер проверяет подпись Telegram `initData` (HMAC по токену бота) и срок её действия;
  `initDataUnsafe` для авторизации не используется. Админ — из `ADMIN_TELEGRAM_IDS`,
  клиент — `client_info/main_client.telegram_id`. Клиентские эндпоинты только читают.
* Роль проверяется дважды: на входе (бот / API) и внутри сервиса.
* `firestore.rules` и `storage.rules` запрещают прямой доступ из браузера; применяются вручную
  (`firebase deploy --only firestore:rules,storage`).
