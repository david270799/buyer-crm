# Сервер Buyer CRM — сведения для агента управления с телефона

Составлено 21.10.2026 по файлам проекта (`docker-compose.yml`, `deploy/setup.sh`, `docs/deploy.md`)
и переписке с владельцем. На сам сервер составитель не заходил: всё, что помечено **«проверить»**,
нужно подтвердить командами из раздела 8. Секретов здесь нет: токен бота, ключ Gemini и остальное
лежат в `/opt/buyer-crm/.env`, ни одной кнопке они не нужны.

## 1. Система
- **ОС:** Ubuntu 24.04, минимальная установка («OS만 설치»), **1 ГБ RAM** + swap 2 ГБ
  (создан `deploy/setup.sh`).
- **Python на сервере:** проверить, `python3 --version`. В Ubuntu 24.04 обычно 3.12, но в минимальной
  установке может не быть. Сама CRM работает в Docker на Python 3.12 и от системного Python не зависит.
- **Пользователь:** `root` (`ssh root@1.234.80.178`). Права полные, `sudo` не нужен.

## 2. Доступ
- **Где:** VPS у корейского хостинга (какого — проверить).
- **Подключение:** SSH (из Windows CMD).
- **IP:** `1.234.80.178` (публичный). Домен — проверить: переменная `DOMAIN` в `.env`, Caddy
  получает для него HTTPS-сертификат.
- **Открытые порты у хостинга:** 22, 80, 443 (со слов владельца).
- **VPN** (Tailscale, ZeroTier, Cloudflare Tunnel): не упоминается, проверить.
- **Занятые порты:** 22 — SSH; 80 и 443 — Caddy (Docker); 8080 — CRM, но только внутри Docker-сети.
  Порт 8765 должен быть свободен (проверить), но у хостинга он, скорее всего, закрыт — см. раздел 7.

## 3. Приложения
Одно приложение — **Buyer CRM**: Telegram-бот + HTTP API + Mini App в одном процессе, перед ним Caddy (HTTPS).

| | |
|---|---|
| Папка | `/opt/buyer-crm` |
| Стек | Python 3.12 (FastAPI, aiogram), React; всё собирается в Docker-образ |
| Как работает | `docker compose`, контейнеры `crm` и `caddy`, `restart: unless-stopped` — поднимаются сами после перезагрузки (если Docker в автозапуске, как ставит `get.docker.com`) |
| Данные | Docker-том `crm_data` (`/data` в контейнере): база `crm.sqlite3`, фото `media/`, копии `backups/` (14 последних) |
| Логи | пишет Docker, отдельных файлов нет |
| Код | git, `github.com/david270799/buyer-crm`, ветка `main`; по инструкции — SSH deploy-ключ только для чтения, без пароля, `git pull` ничего не спрашивает (проверить: `git remote -v`) |

Команды (из `/opt/buyer-crm`):

| Действие | Команда |
|---|---|
| Запуск со сборкой | `docker compose up -d --build` |
| Остановить / запустить CRM | `docker compose stop crm` / `docker compose start crm` |
| Перезапуск | `docker compose restart crm` |
| Статус | `docker compose ps` |
| Логи CRM | `docker compose logs --tail 200 crm` (для агента без `-f`, иначе команда не закончится) |
| Логи Caddy | `docker compose logs --tail 100 caddy` |
| Проверка настроек (ничего не меняет) | `docker compose exec -T crm python -m crm.tools.doctor` |
| Копия базы / список копий | `docker compose exec -T crm python -m crm.tools.backup` / `… --list` |

## 4. Обновление
- Одной командой: `cd /opt/buyer-crm && git pull && docker compose up -d --build`.
- То же есть кнопкой в самой CRM: Mini App → «Настройки» → «Обновить CRM» (если на сервере
  выполнен `bash deploy/install-updater.sh`; служба `crm-updater.path`).
- Миграций нет: CRM читает базу при старте.
- Сборка идёт внутри `--build`; на 1 ГБ это **3–10 минут** — агенту нужен большой таймаут.
- Бэкап перед обновлением сам не делается (ночная копия уходит в Telegram в 04:00 по Сеулу).
  В кнопке «Обновить CRM» первым шагом стоит `crm.tools.backup`.
- **Требуют ввода с клавиатуры — в кнопки не включать:** `bash deploy/setup.sh` (спрашивает токены),
  `nano .env`. В остальных командах ввода нет. Для `docker compose exec` из агента нужен ключ `-T`.
- Обновление системы в проекте не описано. Без вопросов:
  `apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade`.
- Восстановление базы из копии — только вручную по `docs/deploy.md`, раздел «Копии и
  восстановление»: нужно положить файл на сервер и остановить CRM, ошибка может стоить данных.

## 5. Частые команды
Из `/opt/buyer-crm`:
- `git pull && docker compose up -d --build` — обновление, почти после каждого изменения;
- `docker compose logs -f crm` — логи;
- `docker compose exec crm python -m crm.tools.doctor` — проверка;
- `python -m crm.tools.backup` / `--list` (внутри контейнера) — копии.

**Опасные, с подтверждением:** перезапуск и остановка CRM, обновление CRM, восстановление базы,
`apt upgrade`, перезагрузка сервера, чистка Docker-образов.

**Свои скрипты:** только `deploy/setup.sh` (интерактивный, для первой установки).

## 6. Диагностика
`docker compose ps`; логи `crm` и `caddy`; `doctor` (настройки, база, копии, ключ Gemini);
`df -h /` и `docker system df` (диск); `free -m` (память — на 1 ГБ важно); `ss -tlnp` (порты).

## 7. Безопасность
Агент будет работать от `root`: полный терминал с телефона = полный доступ к серверу и к `.env`
с токеном бота. Рекомендуется:
- **только кнопки**, произвольные команды выключить;
- **порт 8765 не открывать в интернет**: лучше Tailscale (агент слушает только адрес Tailscale,
  телефон в той же сети). Если открывать — только за Caddy с HTTPS и длинным токеном доступа.

## 8. Проверить на сервере (ничего не меняет)
```
python3 --version; docker --version; docker compose version
cd /opt/buyer-crm && git remote -v && git status -sb
ss -tlnp
df -h /; free -m
which tailscale cloudflared zerotier-cli
```

## 9. Кнопки
Тот же список лежит отдельно в `deploy/agent-actions.json`.

```json
{
  "default_cwd": "/opt/buyer-crm",
  "actions": [
    {"id": "crm-status", "name": "Статус", "group": "Buyer CRM", "command": "docker compose ps", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "crm-logs", "name": "Логи CRM", "description": "последние 200 строк", "group": "Buyer CRM", "command": "docker compose logs --tail 200 crm", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "caddy-logs", "name": "Логи Caddy (HTTPS)", "group": "Buyer CRM", "command": "docker compose logs --tail 100 caddy", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "crm-doctor", "name": "Проверка настроек", "description": "doctor: настройки, база, копии, ключ Gemini; ничего не меняет", "group": "Buyer CRM", "command": "docker compose exec -T crm python -m crm.tools.doctor", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "crm-version", "name": "Какая версия стоит", "group": "Buyer CRM", "command": "git log --oneline -5 && git status -sb", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "crm-backup", "name": "Сделать копию базы", "group": "Buyer CRM", "command": "docker compose exec -T crm python -m crm.tools.backup", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "crm-backup-list", "name": "Список копий", "group": "Buyer CRM", "command": "docker compose exec -T crm python -m crm.tools.backup --list", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "crm-update", "name": "Обновить CRM", "description": "копия базы → git pull → пересборка; 3–10 минут", "group": "Buyer CRM", "command": "docker compose exec -T crm python -m crm.tools.backup && git pull && docker compose up -d --build", "cwd": "/opt/buyer-crm", "confirm": true},
    {"id": "crm-restart", "name": "Перезапустить CRM", "group": "Buyer CRM", "command": "docker compose restart crm", "cwd": "/opt/buyer-crm", "confirm": true},
    {"id": "crm-stop", "name": "Остановить CRM", "description": "бот и Mini App перестанут работать", "group": "Buyer CRM", "command": "docker compose stop crm", "cwd": "/opt/buyer-crm", "confirm": true},
    {"id": "crm-start", "name": "Запустить CRM", "group": "Buyer CRM", "command": "docker compose start crm", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "sys-disk", "name": "Место на диске", "group": "Сервер", "command": "df -h / && docker system df", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "sys-mem", "name": "Память и нагрузка", "group": "Сервер", "command": "free -m && uptime", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "sys-ports", "name": "Занятые порты", "group": "Сервер", "command": "ss -tlnp", "cwd": "/opt/buyer-crm", "confirm": false},
    {"id": "docker-prune", "name": "Почистить старые образы", "description": "удаляет неиспользуемые образы и кеш сборки; база и фото (тома) не трогаются", "group": "Сервер", "command": "docker image prune -af && docker builder prune -af", "cwd": "/opt/buyer-crm", "confirm": true},
    {"id": "sys-upgrade", "name": "Обновить Ubuntu", "group": "Сервер", "command": "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade", "cwd": "/opt/buyer-crm", "confirm": true},
    {"id": "sys-reboot", "name": "Перезагрузить сервер", "description": "CRM поднимется сама после загрузки", "group": "Сервер", "command": "reboot", "cwd": "/", "confirm": true}
  ]
}
```
