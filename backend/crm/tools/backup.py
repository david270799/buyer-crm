"""Backup and restore of the SQLite database (see crm.backup).

python -m crm.tools.backup                 # make a backup now (safe while running)
python -m crm.tools.backup --list          # list backups
python -m crm.tools.backup --restore FILE  # restore: stop the server first
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from crm.backup import list_backups, make_backup, restore_backup
from crm.config import load_settings
from crm.domain.errors import ConfigurationError
from crm.storage import StorageError


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    load_dotenv(find_dotenv(usecwd=True))
    try:
        settings = load_settings(require_bot=False)
    except ConfigurationError as exc:
        print(f"❌ {exc.user_message}", file=sys.stderr)
        return 2
    if settings.storage != "sqlite":
        print("Резервные копии этой командой — только для STORAGE=sqlite.", file=sys.stderr)
        return 2
    now = datetime.now(UTC)
    try:
        if args[:1] == ["--list"]:
            backups = list_backups(settings.backup_dir)
            for path in backups:
                print(f"{path.name}  {path.stat().st_size // 1024} КБ")
            if not backups:
                print(f"Копий пока нет ({settings.backup_dir}).")
            return 0
        if args[:1] == ["--restore"]:
            if len(args) != 2:
                print("Укажите файл: python -m crm.tools.backup --restore ФАЙЛ", file=sys.stderr)
                return 2
            kept = restore_backup(Path(args[1]), settings.database_path, now)
            print(f"✅ База восстановлена из {args[1]}.")
            if kept:
                print(f"Прежняя база сохранена как {kept}.")
            print("Запустите CRM снова.")
            return 0
        archive = make_backup(
            settings.database_path, settings.backup_dir, now, keep=settings.backup_keep
        )
        print(f"✅ Копия: {archive} ({archive.stat().st_size // 1024} КБ)")
        return 0
    except StorageError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
