# Запуск в работу

Всё работает одним сервисом на вашем сервере: API, Mini App (клиент и админ), Telegram-бот и база.
Telegram открывает Mini App только по **HTTPS**, поэтому нужен сервер с доменом.

## Где хранятся данные

По умолчанию (`STORAGE=sqlite`) всё лежит на сервере, в одной папке данных (`DATA_DIR`,
в Docker — том `crm_data`, внутри контейнера `/data`):

| Что | Где |
|---|---|
| База (заказы, деньги, история, настройки) | `crm.sqlite3` — один файл SQLite |
| Фото заказов и отправок | `media/` (WebP, до ~0,5 МБ на фото) |
| Резервные копии базы | `backups/crm-ДАТА-ВРЕМЯ.sqlite3.gz`, хранятся последние 14 |

Каждую ночь в 4:00 (Сеул) бот делает копию базы и **присылает её администраторам в Telegram** —
так копия всегда есть не только на сервере. Фото в копию не входят (их много, и их можно
прислать заново); всё о заказах и деньгах — входит. Отключить отправку: `BACKUP_TO_TELEGRAM=0`.

30 ГБ диска хватает надолго: база даже для тысяч заказов — десятки мегабайт, фото — около
0,5 МБ, то есть это десятки тысяч фото.

## Свой сервер (VPS) с Docker

Подойдёт любой VPS с Ubuntu 24.04 (1 vCPU, 2 ГБ RAM; на 1 ГБ скрипт сам добавит swap) и открытыми
портами 22, 80, 443. Для Mini App нужен ещё домен или поддомен (`crm.example.com`) с A-записью
на IP сервера; бот работает и без него, домен можно добавить позже.

1. Зайдите на сервер: `ssh root@IP_СЕРВЕРА` (macOS — «Терминал», Windows — PowerShell).
2. Дайте серверу доступ к репозиторию (он приватный) — ключом только для чтения:
   ```bash
   apt-get update && apt-get install -y git
   ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C crm-server
   cat ~/.ssh/id_ed25519.pub
   ```
   Строку `ssh-ed25519 …` добавьте на GitHub: репозиторий → **Settings → Deploy keys → Add deploy key**
   (галочку «Allow write access» не ставьте). Это открытая часть ключа, её можно показывать;
   файл `id_ed25519` без `.pub` никуда не копируйте.
3. Скачайте проект и запустите установку:
   ```bash
   ssh-keyscan github.com >> ~/.ssh/known_hosts
   git clone git@github.com:<владелец>/buyer-crm.git /opt/buyer-crm
   cd /opt/buyer-crm && bash deploy/setup.sh
   ```
   Скрипт ставит Docker, спрашивает токен бота, ваш Telegram ID, ключ Gemini и домен (токен и ключ
   при вводе не видны), записывает их в `.env` и запускает CRM. Запускать его повторно безопасно —
   так же добавляются домен или ID позже; уже заполненное не спрашивается (исправить: `nano .env`).
   Вручную то же самое: Docker (`curl -fsSL https://get.docker.com | sh`), `cp .env.example .env`,
   заполнить, `chmod 600 .env`, `docker compose up -d --build`.
4. Проверка:
   ```bash
   docker compose logs -f crm      # «Bot @... started», «SQLite database: /data/crm.sqlite3»
   docker compose exec crm python -m crm.tools.doctor    # проверка, ничего не меняет
   ```
5. Откройте бота в Telegram → `/start` → кнопка **«CRM»** (бот ставит её сам, если задан домен).
6. В @BotFather выключите Privacy Mode (`/setprivacy` → Disable), добавьте бота в группу с клиентом
   (сами, с выключенной «анонимностью») и ответьте `/setclient` на любое сообщение клиента.
   С этого момента каждое фото с подписью от клиента или его помощников молча становится заказом;
   вопросы бот присылает вам в личку.

Один токен — один работающий бот: если CRM запущена у вас на компьютере, остановите её там.

Обновление после изменений в коде: `cd /opt/buyer-crm && git pull && docker compose up -d --build` —
данные в томе `crm_data` сохраняются.

## Копии и восстановление

```bash
docker compose exec crm python -m crm.tools.backup           # сделать копию сейчас
docker compose exec crm python -m crm.tools.backup --list    # список копий
docker compose cp crm:/data/backups ./backups                # скачать копии с сервера
```

Восстановление (например, из файла, который бот прислал в Telegram):

```bash
docker compose cp crm-20261001-040000.sqlite3.gz crm:/data/restore.sqlite3.gz
docker compose stop crm
docker compose run --rm crm python -m crm.tools.backup --restore /data/restore.sqlite3.gz
docker compose start crm
```

Перед заменой копия проверяется; прежняя база остаётся рядом как `crm.sqlite3.before-restore-…`.
Пока сервер работает, восстановление отказывается запускаться — база открыта.

Свои отчёты можно строить обычным SQL: в базе есть представления `orders_v` и `transactions_v`,
например `sqlite3 crm.sqlite3 "select status, count(*), sum(profit) from orders_v group by status"`
(на копии или при остановленном сервере).

## Без Docker

То же самое работает напрямую: `cd backend && python -m crm.server` — база и фото появятся в папке
`data/` в корне проекта (или в `DATA_DIR`). Нужен только один запущенный процесс CRM на одну базу:
второй откажется стартовать, пока первый работает.

## Firebase вместо SQLite (необязательно)

`STORAGE=firestore` хранит данные в Firestore, а фото в Firebase Storage — тогда нужны
`FIREBASE_PROJECT_ID`, `FIREBASE_STORAGE_BUCKET` и ключ сервисного аккаунта (`FIREBASE_CREDENTIALS`,
в docker-compose раскомментируйте строку с `secrets/service-account.json`). Резервные копии
тогда делает Google. Этот вариант также позволяет запуск в Google Cloud Run
(`--min-instances 1 --max-instances 1 --no-cpu-throttling`), где нет постоянного диска.
Правила `firestore.rules` и `storage.rules` запрещают прямой доступ из браузера:
`firebase deploy --only firestore:rules,storage`.

## Ключи и безопасность

* Ключи хранятся только в `.env` на сервере. В git и в чаты их не отправляйте.
* Перевыпуск: токен бота — @BotFather → `/revoke`; ключ Gemini — AI Studio. После замены — `docker compose up -d`.
* Копия базы содержит все заказы и деньги — присылается только администраторам в личку.
  Не пересылайте её никому.
* Один бот-токен — один работающий экземпляр. Для экспериментов заведите отдельного тестового бота
  и запускайте `python -m crm.server --demo` — демо-данные в памяти, настоящая база не затрагивается.
