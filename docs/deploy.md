# Запуск в работу

Всё работает одним сервисом: API, Mini App (клиент и админ) и Telegram-бот.
Telegram открывает Mini App только по **HTTPS**, поэтому нужен сервер с доменом.

## Вариант 1 — свой сервер (VPS) с Docker — рекомендуется

Подойдёт любой VPS за ~$5/мес (1 vCPU, 1 ГБ RAM) и домен или поддомен, например `crm.example.com`.

1. В DNS направьте `crm.example.com` на IP сервера (A-запись).
2. Установите Docker: `curl -fsSL https://get.docker.com | sh`.
3. Скопируйте проект и настройки:
   ```bash
   git clone <адрес репозитория> buyer-crm && cd buyer-crm
   cp .env.example .env            # заполните BOT_TOKEN, ADMIN_TELEGRAM_IDS, DOMAIN, MINI_APP_URL,
                                   # FIREBASE_PROJECT_ID, FIREBASE_STORAGE_BUCKET, GEMINI_API_KEY
   mkdir -p secrets && nano secrets/service-account.json   # JSON сервисного аккаунта Firebase
   chmod 600 .env secrets/service-account.json
   ```
4. Проверка данных Firebase (ничего не пишет):
   ```bash
   docker compose run --rm crm python -m crm.tools.doctor
   ```
5. Запуск:
   ```bash
   docker compose up -d --build
   docker compose logs -f crm      # «Bot @... started», «Uvicorn running»
   ```
6. Откройте бота в Telegram → `/start` → кнопка **«CRM»** (бот ставит её сам, если задан `MINI_APP_URL`).
   Клиент открывает ту же кнопку из лички с ботом и видит только свой режим.

7. В @BotFather выключите Privacy Mode (`/setprivacy` → Disable), добавьте бота в группу с клиентом
   (сами, с выключенной «анонимностью») и ответьте `/setclient` на любое сообщение клиента.
   С этого момента каждое фото клиента с подписью становится заказом.

Обновление после изменений в коде: `git pull && docker compose up -d --build`.

Пошаговая инструкция со скриншотами, включая проверку на своём компьютере через временный
HTTPS-туннель, — [guide.pdf](guide.pdf).

## Вариант 2 — Google Cloud Run (тот же Google-аккаунт, что и Firebase)

Требуется тариф Blaze. Бот работает через long polling, поэтому нужен ровно **один постоянно работающий** экземпляр:

```bash
gcloud run deploy buyer-crm --source . --region asia-northeast3 \
  --min-instances 1 --max-instances 1 --no-cpu-throttling \
  --set-env-vars ADMIN_TELEGRAM_IDS=...,FIREBASE_PROJECT_ID=...,FIREBASE_STORAGE_BUCKET=... \
  --set-secrets BOT_TOKEN=bot-token:latest
```

На Cloud Run сервисный аккаунт подключается автоматически (Application Default Credentials),
JSON-ключ не нужен. `MINI_APP_URL` — адрес сервиса, который выдаст `gcloud`.

## Firebase

* **Правила доступа** (`firestore.rules`, `storage.rules`) запрещают всё для браузеров — backend
  работает через Admin SDK и их не использует. Применить: `firebase deploy --only firestore:rules,storage`.
  Перед этим убедитесь, что к Firestore не обращается напрямую никакое другое приложение.
* **Storage**: включите Firebase Storage в консоли и укажите бакет в `FIREBASE_STORAGE_BUCKET` —
  иначе загрузка фото в Mini App будет отключена (остальное работает).

## Ключи и безопасность

* Ключи хранятся только в `.env` / `secrets/` на сервере (или в Secret Manager). В git и в чаты их не отправляйте.
* Перевыпуск: токен бота — @BotFather → `/revoke`; ключ Firebase — Google Cloud Console →
  IAM → Service accounts → Keys → удалить старый, создать новый. После замены — `docker compose up -d`.
* Один бот-токен — один работающий экземпляр. Для экспериментов заведите отдельного тестового бота
  и запускайте `python -m crm.server --demo` — демо-данные в памяти, Firebase не затрагивается.
