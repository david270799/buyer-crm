# Перенос CRM на домашний мини-ПК (Ryzen Embedded R2544, 16 ГБ, SSD 250 ГБ)

Составлено 22.10.2026. Секретов здесь нет: токен бота, ключ Gemini и пароли вводятся только на
серверах, в чат их не присылать.

## Какую систему ставить

**Ubuntu Server 24.04 LTS** — та же система, что на нынешнем VPS: все наши скрипты (`deploy/setup.sh`,
`deploy/install-updater.sh`) работают без изменений, обновления безопасности — до 2029 года.
Без рабочего стола: он только съедает память.

Каждое приложение — в своём Docker-контейнере (как CRM сейчас): приложения не мешают друг другу,
ставятся и удаляются одной командой, переносятся на другой компьютер вместе с данными.
Чтобы смотреть и перезапускать контейнеры из браузера, можно поставить **Dockge** или **Portainer**.

Альтернатива — **Proxmox VE**: если понадобятся целые виртуальные машины (например, Windows рядом
с Linux). Он сложнее, для ботов и сайтов не нужен.

### Сколько приложений поместится

| Что | Памяти | Сколько влезет в 16 ГБ |
|---|---|---|
| Наша CRM (бот + API + Mini App) | ~200–300 МБ | — |
| Небольшой бот на Python / Node.js | 50–150 МБ | десятки |
| Небольшой сайт или API + база | 200–500 МБ | 15–30 |
| Тяжёлые (Nextcloud, медиасервер, ИИ-модели) | 1–4 ГБ | 2–4 |

Реально с запасом: **20–30 небольших ботов и сайтов** одновременно. 8 потоков процессора
справятся — такие приложения почти всё время ждут сообщений. 250 ГБ хватит надолго; растут
обычно фото и копии.

## Что нужно заранее

- флешка на 8 ГБ и компьютер с Windows (записать установщик программой **Rufus**);
- монитор и клавиатура — только на время установки;
- **кабель в роутер** (не Wi-Fi);
- домен в Cloudflare (бесплатный аккаунт): если домена нет, его можно купить у любого регистратора,
  потом в Cloudflare «Add a site» и поменять у регистратора NS-серверы на те, что даст Cloudflare.

## Шаг 1. Поставить Ubuntu Server

1. Скачать «Ubuntu Server 24.04 LTS» с ubuntu.com, записать на флешку через Rufus.
2. Загрузиться с флешки (при включении F7/F11/F12 или Del → Boot), установить:
   язык English, весь диск, **отметить «Install OpenSSH server»**, придумать имя и пароль.
3. В BIOS найти **«Restore on AC Power Loss» → Power On**: после отключения света ПК включится сам.
4. В роутере закрепить за мини-ПК постоянный адрес (DHCP reservation), например `192.168.0.50`.
5. Дальше всё — с компьютера через SSH: `ssh имя@192.168.0.50`, затем `sudo -i` (стать root).

## Шаг 2. Docker и код CRM

```bash
apt-get update && apt-get -y upgrade && apt-get install -y git
curl -fsSL https://get.docker.com | sh
```

Доступ к репозиторию — новый deploy-ключ для этого компьютера (как в `docs/deploy.md`, шаг 2):

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C crm-home
cat ~/.ssh/id_ed25519.pub        # эту строку — в GitHub: Settings → Deploy keys → Add (без write access)
ssh-keyscan github.com >> ~/.ssh/known_hosts
git clone git@github.com:david270799/buyer-crm.git /opt/buyer-crm
```

## Шаг 3. Остановить CRM на VPS и забрать данные

Один токен бота — один работающий бот, поэтому сначала выключаем старый.
**На VPS** (`ssh root@1.234.80.178`):

```bash
cd /opt/buyer-crm
docker compose exec -T crm python -m crm.tools.backup      # копия базы на всякий случай
docker compose stop crm
docker volume ls | grep crm_data                            # имя тома, обычно buyer-crm_crm_data
docker run --rm -v buyer-crm_crm_data:/data -v /root:/out alpine tar czf /out/crm-data.tgz -C /data .
```

В архиве `crm-data.tgz` всё: база, фото заказов и витрины, копии.

**На мини-ПК** (root) — забрать архив и настройки (спросит пароль VPS; файл `.env` на экран не выводится):

```bash
scp root@1.234.80.178:/root/crm-data.tgz /root/
scp root@1.234.80.178:/opt/buyer-crm/.env /opt/buyer-crm/.env
chmod 600 /opt/buyer-crm/.env
docker volume create buyer-crm_crm_data
docker run --rm -v buyer-crm_crm_data:/data -v /root:/in alpine tar xzf /in/crm-data.tgz -C /data
```

## Шаг 4. Адрес для Mini App (Cloudflare Tunnel)

Дома нет постоянного внешнего адреса и открытых портов, поэтому HTTPS даёт Cloudflare: туннель сам
соединяется с Cloudflare изнутри, ничего открывать в роутере не нужно.

1. dash.cloudflare.com → **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**,
   имя `crm-home`.
2. Cloudflare покажет команду установки для Debian/Ubuntu. Она содержит **секретный токен**:
   выполнить её на мини-ПК, никуда не пересылать.
3. **Public Hostname**: поддомен `crm`, ваш домен, **Service: HTTP**, URL `localhost:80`. Сохранить.
4. В `.env` на мини-ПК (`nano /opt/buyer-crm/.env`):
   - `DOMAIN=` — **пусто** (сертификат делает Cloudflare, Caddy работает по HTTP внутри);
   - `MINI_APP_URL=https://crm.ваш-домен/` — адрес из пункта 3.

## Шаг 5. Запустить

```bash
cd /opt/buyer-crm
docker compose up -d --build
docker compose logs --tail 50 crm                  # «Bot @... started», «SQLite database: /data/crm.sqlite3»
docker compose exec -T crm python -m crm.tools.doctor
bash deploy/install-updater.sh                     # кнопка «Обновить CRM» в Mini App
```

Проверить в Telegram: бот отвечает, Mini App открывается, у заказов есть фото, баланс тот же.

## Шаг 6. После переноса

- Недели две VPS не удалять: если дома что-то пойдёт не так — `docker compose start crm` на VPS
  (а на мини-ПК `docker compose stop crm`), и всё вернётся. Потом VPS можно отключить.
- Ночные копии базы по-прежнему приходят вам в Telegram.
- Обновления CRM — кнопкой в Mini App; обновления системы — `apt-get update && apt-get -y upgrade`
  раз в месяц (или включить автоматические: `apt-get install -y unattended-upgrades`).
- Желательно небольшой ИБП: короткие отключения света не будут перезагружать сервер.

## Новые приложения рядом

Каждое — в своей папке `/opt/имя` со своим `docker-compose.yml`; запуск `docker compose up -d`.
Если у приложения есть веб-страница — ещё один **Public Hostname** в том же туннеле
(`app2.ваш-домен` → `http://localhost:ПОРТ`), порт у каждого свой (не 80 — он занят CRM).
