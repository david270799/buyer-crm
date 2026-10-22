#!/usr/bin/env bash
# Включает кнопку «Обновить CRM» в Mini App (21.10.2026). Запускать один раз на сервере:
#
#   cd /opt/buyer-crm && bash deploy/install-updater.sh
#
# Ставит две маленькие службы systemd. crm-updater.path ничего не делает, пока
# CRM не положит заявку request.json; тогда crm-updater.service выполняет
# deploy/updater.sh (git pull && docker compose up -d --build). Ресурсов в простое
# не тратит. Повторный запуск безопасен. Убрать: systemctl disable --now crm-updater.path

set -euo pipefail
cd "$(dirname "$0")/.."
repo="$(pwd)"

container="$(docker compose ps -q crm)"
if [ -z "$container" ]; then
  echo "CRM не запущена. Сначала: docker compose up -d --build" >&2
  exit 1
fi
data="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$container")"
if [ -z "$data" ]; then
  echo "Не нашёл папку данных CRM (/data)." >&2
  exit 1
fi
dir="$data/update"
mkdir -p "$dir"
chmod 777 "$dir"  # CRM в контейнере кладёт сюда заявку
chmod +x "$repo/deploy/updater.sh"

cat >/etc/systemd/system/crm-updater.service <<EOF
[Unit]
Description=Buyer CRM: обновление по кнопке из Mini App
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/env bash $repo/deploy/updater.sh $dir
TimeoutStartSec=1800
EOF

cat >/etc/systemd/system/crm-updater.path <<EOF
[Unit]
Description=Buyer CRM: ждёт заявку на обновление из Mini App

[Path]
PathExists=$dir/request.json
Unit=crm-updater.service

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now crm-updater.path >/dev/null
date -u +%Y-%m-%dT%H:%M:%SZ >"$dir/installed"
chmod 644 "$dir/installed"
echo "✅ Готово: кнопка «Обновить CRM» в Mini App (Настройки) работает."
