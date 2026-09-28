#!/usr/bin/env bash
# Установка и запуск CRM на сервере Ubuntu. Из папки проекта, от root:
#
#   bash deploy/setup.sh
#
# Что делает:
#   1. на сервере с 1–2 ГБ памяти добавляет swap 2 ГБ (иначе сборка может упасть);
#   2. ставит Docker, если его нет;
#   3. спрашивает токен бота, ваш Telegram ID, ключ Gemini и домен и записывает
#      их в .env (токен и ключ при вводе не видны на экране);
#   4. собирает и запускает CRM (docker compose) и показывает, запустился ли бот.
#
# Запускать повторно безопасно: заполненные строки .env и данные (том crm_data)
# не трогаются, спрашивается только то, что ещё пусто. Исправить значение:
# nano .env, затем снова bash deploy/setup.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

title() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
warn() { printf '\033[33m⚠️  %s\033[0m\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Запустите от root: sudo bash deploy/setup.sh"
  exit 1
fi

# --- 1. swap -------------------------------------------------------------------
mem_mb=$(awk '/^MemTotal:/ {print int($2 / 1024)}' /proc/meminfo)
if [ "$mem_mb" -lt 3000 ] && [ -z "$(swapon --show --noheadings)" ]; then
  title "Добавляю swap 2 ГБ (памяти на сервере ${mem_mb} МБ)"
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

# --- 2. Docker -----------------------------------------------------------------
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  title "Устанавливаю Docker (1–3 минуты)"
  command -v curl >/dev/null || { apt-get update -q && apt-get install -yq curl; }
  curl -fsSL https://get.docker.com | sh
fi

# --- 3. Настройки (.env) -------------------------------------------------------
umask 077
[ -f .env ] || cp .env.example .env
chmod 600 .env

get_env() { grep -m1 "^$1=" .env | cut -d= -f2- || true; }

set_env() {
  if grep -q "^$1=" .env; then
    KEY="$1" VALUE="$2" awk '{
      if (index($0, ENVIRON["KEY"] "=") == 1) print ENVIRON["KEY"] "=" ENVIRON["VALUE"]
      else print
    }' .env >.env.new
    mv .env.new .env
  else
    printf '%s=%s\n' "$1" "$2" >>.env
  fi
  chmod 600 .env
}

# ask NAME REGEX hidden|visible required|optional → the value, without spaces
ask() {
  local value
  while true; do
    if [ "$3" = hidden ]; then
      read -rsp "$1: " value || { echo "Нет ввода — запустите скрипт в терминале." >&2; return 1; }
      echo >&2
    else
      read -rp "$1: " value || { echo "Нет ввода — запустите скрипт в терминале." >&2; return 1; }
    fi
    value=$(printf '%s' "$value" | tr -d '[:space:]')
    if [ -z "$value" ] && [ "$4" = optional ]; then break; fi
    if [[ $value =~ $2 ]]; then break; fi
    echo "Не похоже на правильное значение — попробуйте ещё раз." >&2
  done
  printf '%s' "$value"
}

public_ip=$(curl -fsS -m 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')

if [ -z "$(get_env BOT_TOKEN)" ]; then
  title "Токен бота"
  echo "Скопируйте токен из @BotFather, вставьте сюда и нажмите Enter."
  echo "Символы на экране не появятся — так и задумано."
  token=$(ask BOT_TOKEN '^[0-9]{5,}:[A-Za-z0-9_-]{30,}$' hidden required)
  set_env BOT_TOKEN "$token"
  echo "✅ Токен сохранён (…${token: -4})"
fi

if [ -z "$(get_env ADMIN_TELEGRAM_IDS)" ]; then
  title "Ваш Telegram ID"
  echo "Число, которое бот показывает на /start (несколько — через запятую)."
  echo "Не знаете — нажмите Enter: после запуска напишите боту /start и запустите скрипт ещё раз."
  ids=$(ask ADMIN_TELEGRAM_IDS '^[0-9]{3,}(,[0-9]{3,})*$' visible optional)
  if [ -n "$ids" ]; then set_env ADMIN_TELEGRAM_IDS "$ids"; fi
fi

if [ -z "$(get_env GEMINI_API_KEY)" ]; then
  title "Ключ Gemini (распознавание товара на фото)"
  echo "Ключ из https://aistudio.google.com/apikey. Символы не видны. Нет ключа — Enter:"
  echo "заказы всё равно принимаются, бренд и модель тогда впишете сами."
  key=$(ask GEMINI_API_KEY '^[A-Za-z0-9_-]{20,}$' hidden optional)
  if [ -n "$key" ]; then
    set_env GEMINI_API_KEY "$key"
    echo "✅ Ключ сохранён (…${key: -4})"
  fi
fi

if [ -z "$(get_env DOMAIN)" ]; then
  title "Домен для Mini App"
  echo "Telegram открывает Mini App только по HTTPS, а для него нужен домен (например crm.example.com),"
  echo "у которого A-запись указывает на IP этого сервера: ${public_ip}."
  echo "Домена пока нет — нажмите Enter: бот заработает сразу, Mini App подключите позже."
  domain=$(ask DOMAIN '^(https?://)?([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}/?$' visible optional)
  domain=${domain#http://}
  domain=${domain#https://}
  domain=$(printf '%s' "${domain%/}" | tr '[:upper:]' '[:lower:]')
  if [ -n "$domain" ]; then
    set_env DOMAIN "$domain"
    set_env MINI_APP_URL "https://${domain}/"
  fi
fi

domain=$(get_env DOMAIN)
if [ -n "$domain" ]; then
  resolved=$(getent ahostsv4 "$domain" | awk 'NR == 1 {print $1}' || true)
  if [ "$resolved" != "$public_ip" ]; then
    warn "Домен ${domain} указывает на «${resolved:-никуда}», а IP сервера ${public_ip}."
    warn "Исправьте A-запись у регистратора. Сертификат HTTPS получится, когда она обновится."
  fi
fi

# --- 4. Запуск -----------------------------------------------------------------
title "Собираю и запускаю CRM (первый раз 3–10 минут)"
echo "Если CRM с этим же ботом запущена у вас на компьютере — остановите её там (Ctrl+C):"
echo "один бот может работать только в одном месте."
docker compose up -d --build
docker image prune -f >/dev/null 2>&1 || true

title "Проверка"
status=""
for _ in $(seq 1 45); do
  logs=$(docker compose logs crm 2>&1 || true)
  if grep -q "Bot @.* started" <<<"$logs"; then status=ok; break; fi
  if grep -qE "Бот остановлен|Ошибка конфигурации|Traceback" <<<"$logs"; then status=failed; break; fi
  sleep 2
done

docker compose logs --tail 15 crm
echo
if [ "$status" = ok ]; then
  echo "✅ CRM и бот работают. Данные — в томе Docker crm_data, копия базы каждую ночь придёт вам в Telegram."
elif [ "$status" = failed ]; then
  warn "CRM или бот не запустились — причина в последних строках выше. Частые: неверный токен"
  warn "(исправьте BOT_TOKEN: nano .env) или бот уже запущен где-то ещё. Затем: bash deploy/setup.sh"
else
  warn "Бот ещё не ответил. Посмотрите журнал: docker compose logs -f crm (выход — Ctrl+C)."
fi

if [ -z "$(get_env ADMIN_TELEGRAM_IDS)" ]; then
  echo "👉 Напишите боту /start — он покажет ваш ID. Затем снова: bash deploy/setup.sh"
fi
if [ -n "$domain" ]; then
  echo "📱 Mini App: https://${domain}/ — в Telegram: бот → /start → кнопка «CRM»."
else
  echo "📱 Mini App пока без домена. Когда появится домен — снова: bash deploy/setup.sh"
fi
echo
echo "Журнал:     docker compose logs -f crm"
echo "Проверка:   docker compose exec crm python -m crm.tools.doctor"
echo "Обновление: git pull && docker compose up -d --build"
