#!/usr/bin/env bash
# «Обновить CRM» из Mini App. Запускает systemd (crm-updater.service), когда CRM
# кладёт заявку request.json в папку обновлений; ставится deploy/install-updater.sh.
#
# Делает то же, что владелец руками: git pull && docker compose up -d --build,
# и пишет итог в status.json (его показывает Mini App), вывод — в update.log.
#
# Всё тело — в функции: git pull меняет и этот файл, а bash читает скрипт по ходу
# выполнения; функция целиком прочитана до первой команды.

main() {
  set -uo pipefail
  local dir="$1"
  local repo
  repo="$(cd "$(dirname "$0")/.." && pwd)"
  local request="$dir/request.json"
  [ -f "$request" ] || return 0
  mv -f "$request" "$dir/taken.json"

  local before after started code state
  before="$(git -C "$repo" rev-parse --short HEAD 2>/dev/null || echo "")"
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  status "$dir" running "$started" "" "$before" "" ""

  {
    echo "== $(date -u) обновление: git pull && docker compose up -d --build"
    cd "$repo" && git pull --ff-only && docker compose up -d --build
  } >"$dir/update.log" 2>&1
  code=$?

  after="$(git -C "$repo" rev-parse --short HEAD 2>/dev/null || echo "")"
  state=done
  [ "$code" -eq 0 ] || state=failed
  status "$dir" "$state" "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$before" "$after" "$code"
  rm -f "$dir/taken.json"
}

status() {  # dir state started finished before after exit_code
  local tmp="$1/status.json.tmp"
  printf '{"state":"%s","started_at":"%s","finished_at":"%s","before":"%s","after":"%s","exit_code":"%s"}\n' \
    "$2" "$3" "$4" "$5" "$6" "$7" >"$tmp"
  chmod 644 "$tmp"
  mv -f "$tmp" "$1/status.json"
}

main "$@"
exit $?
