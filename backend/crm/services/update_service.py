"""«Обновить CRM» from the Mini App (the owner, 21.10.2026).

The CRM runs in a Docker container and cannot rebuild itself: the update stops
the very container that would run it. So the Mini App only leaves a request
file in the data folder; a tiny systemd unit on the server itself
(`deploy/install-updater.sh`) wakes up on that file, runs the usual
`git pull && docker compose up -d --build` and writes the outcome back:

* `request.json` — written here, taken by the server's updater;
* `status.json`  — written by the updater: `state` running / done / failed,
  `started_at`, `finished_at`, `before`, `after` (commit hashes), `exit_code`;
* `update.log`   — the command's output (its tail is shown on failure);
* `installed`    — the updater is installed (`install-updater.sh` puts it).

The container gets no access to Docker or to the host: it only writes a file.
"""

import json
from pathlib import Path
from typing import Any

from crm.domain.errors import ConflictError
from crm.services.common import Actor, Auditor, Clock, require_admin
from crm.storage import Database, Transaction

LOG_TAIL_LINES = 40


class UpdateService:
    def __init__(self, db: Database, clock: Clock, auditor: Auditor, folder: Path | None):
        self._db = db
        self._clock = clock
        self._auditor = auditor
        self._folder = folder

    def status(self, actor: Actor) -> dict[str, Any]:
        require_admin(actor)
        folder = self._folder
        if folder is None or not (folder / "installed").exists():
            return {"installed": False, "state": "idle", "requested": False}
        status = _read_json(folder / "status.json")
        result: dict[str, Any] = {
            "installed": True,
            "requested": (folder / "request.json").exists(),
            "state": status.get("state") or "idle",
            "started_at": status.get("started_at"),
            "finished_at": status.get("finished_at"),
            "before": status.get("before"),
            "after": status.get("after"),
        }
        if result["state"] == "failed":
            result["log"] = _tail(folder / "update.log", LOG_TAIL_LINES)
        return result

    def request(self, actor: Actor) -> dict[str, Any]:
        """Ask the server to update; refused while an update is waiting or running."""
        current = self.status(actor)
        if not current["installed"]:
            raise ConflictError(
                "Обновление из Mini App ещё не включено на сервере. Один раз выполните на сервере: "
                "cd /opt/buyer-crm && git pull && bash deploy/install-updater.sh"
            )
        if current["requested"] or current["state"] == "running":
            raise ConflictError("Обновление уже идёт — подождите несколько минут.")
        now = self._clock.now()

        def fn(tx: Transaction) -> None:
            self._auditor.record(
                tx,
                actor,
                now,
                action="system.update",
                entity_type="system",
                entity_id="update",
                before={"state": current["state"]},
                after={"requested_at": now.isoformat()},
            )

        self._db.run_transaction(fn)
        assert self._folder is not None  # installed
        temporary = self._folder / "request.json.tmp"
        temporary.write_text(json.dumps({"requested_at": now.isoformat(), "by": actor.id}))
        temporary.replace(self._folder / "request.json")  # appears whole, never half-written
        return {**current, "requested": True}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _tail(path: Path, lines: int) -> str:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])
