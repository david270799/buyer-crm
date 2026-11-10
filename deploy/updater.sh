#!/usr/bin/env bash
# «Обновить CRM» из Mini App. Запускает systemd (crm-updater.service), когда CRM
# кладёт заявку request.json в папку обновлений; ставится deploy/install-updater.sh.
#
# Делает то же, что владелец руками: git pull && docker compose up -d --build,
# и пишет итог в status.json (его показывает Mini App), вывод — в update.log.
#
# Всё тело — в функции: git pull меняет и этот файл, а bash читает скрипт по ходу
# выполнения; функция целиком прочитана до первой команды.

# Безопасность (аудит 10.11.2026): папка обновлений лежит в томе CRM, её
# содержимым управляет контейнер, а этот скрипт работает от root. Чтобы
# подложенная в папку ссылка (symlink) не заставила root перезаписать файл сервера:
#   * сначала cd в папку и проверка, что это она сама, а не ссылка куда-то ещё;
#   * файлы создаются только новыми (noclobber = O_EXCL, по ссылке не пойдёт),
#     под случайным именем, и пишутся через открытый дескриптор;
#   * на место ставятся переименованием (mv -T), удаляются по имени (rm) —
#     обе операции трогают саму ссылку, а не то, на что она указывает.

main() {
  set -uo pipefail
  umask 022
  local dir="$1"
  local repo parent
  repo="$(cd "$(dirname "$0")/.." && pwd)"
  parent="$(cd "$(dirname "$dir")" 2>/dev/null && pwd -P)" || return 0
  cd "$dir" 2>/dev/null || return 0
  if [ "$(pwd -P)" != "$parent/$(basename "$dir")" ]; then
    echo "Папка обновлений $dir подменена ссылкой — обновление не запущено." >&2
    return 1
  fi
  [ -f request.json ] || return 0
  rm -f -- request.json taken.json

  local before after started code state log
  before="$(git -C "$repo" rev-parse --short HEAD 2>/dev/null || echo "")"
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  status running "$started" "" "$before" "" ""

  log=".update.log.$$.$RANDOM$RANDOM"
  set -o noclobber
  if ! { exec 8>"$log"; } 2>/dev/null; then
    set +o noclobber
    echo "Не удалось создать журнал обновления в $dir." >&2
    status failed "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$before" "$before" 1
    return 1
  fi
  set +o noclobber
  mv -f -T -- "$log" update.log
  (
    echo "== $(date -u) обновление: git pull && docker compose up -d --build"
    cd "$repo" && git pull --ff-only && docker compose up -d --build
  ) >&8 2>&1
  code=$?
  exec 8>&-

  after="$(git -C "$repo" rev-parse --short HEAD 2>/dev/null || echo "")"
  state=done
  [ "$code" -eq 0 ] || state=failed
  status "$state" "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$before" "$after" "$code"
}

status() {  # state started finished before after exit_code  (в папке обновлений)
  local tmp=".status.json.$$.$RANDOM$RANDOM"
  (
    set -o noclobber
    printf '{"state":"%s","started_at":"%s","finished_at":"%s","before":"%s","after":"%s","exit_code":"%s"}\n' \
      "$1" "$2" "$3" "$4" "$5" "$6" >"$tmp"
  ) 2>/dev/null && mv -f -T -- "$tmp" status.json
}

main "$@"
exit $?
