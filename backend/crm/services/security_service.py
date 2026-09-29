"""Admin PIN for the Mini App: a lock screen so that someone holding the
owner's unlocked phone does not see the CRM. A convenience, not strong
security (the owner's words: "чисто формальность").

Only a salted PBKDF2 hash is stored (`settings/security`). Wrong attempts
are slowed down: after 5 misses in a row the PIN is not checked for 30 s.
"""

import hashlib
import hmac
import re
import secrets
import threading
import time
from datetime import datetime

from crm.domain.errors import ConflictError, ValidationError
from crm.services.common import Actor, Auditor, Clock, require_admin
from crm.storage import Database, Transaction

COLLECTION = "settings"
DOC_ID = "security"
_PIN_RE = re.compile(r"^\d{4,8}$")
_ITERATIONS = 200_000
_MAX_MISSES = 5
_LOCKOUT_SECONDS = 30


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), _ITERATIONS).hex()


class SecurityService:
    def __init__(self, db: Database, clock: Clock, auditor: Auditor):
        self._db = db
        self._clock = clock
        self._auditor = auditor
        self._lock = threading.Lock()
        self._misses = 0
        self._blocked_until = 0.0

    def pin_set(self, actor: Actor) -> bool:
        return self.pin_length(actor) > 0

    def pin_length(self, actor: Actor) -> int:
        """Digits in the PIN (0 = no PIN): the lock screen enters as soon as they are typed."""
        require_admin(actor)
        doc = self._db.get(COLLECTION, DOC_ID) or {}
        if not doc.get("pin_hash"):
            return 0
        length = doc.get("pin_length")
        return length if isinstance(length, int) else 4

    def set_pin(self, actor: Actor, pin: str | None) -> bool:
        """Set a new PIN (4–8 digits) or remove it (None). Returns whether one is set."""
        require_admin(actor)
        if pin is not None and not _PIN_RE.match(pin):
            raise ValidationError("PIN — от 4 до 8 цифр.")
        now: datetime = self._clock.now()
        salt = secrets.token_hex(16)
        data: dict = {"pin_hash": None, "pin_salt": None, "pin_length": None, "updated_at": now}
        if pin is not None:
            data.update(pin_hash=_hash(pin, salt), pin_salt=salt, pin_length=len(pin))

        def fn(tx: Transaction) -> None:
            tx.set(COLLECTION, DOC_ID, data, merge=True)
            self._auditor.record(
                tx,
                actor,
                now,
                action="security.pin_set" if pin is not None else "security.pin_removed",
                entity_type="settings",
                entity_id=DOC_ID,
                before=None,
                after=None,  # never the PIN or its hash
            )

        self._db.run_transaction(fn)
        with self._lock:
            self._misses = 0
            self._blocked_until = 0.0
        return pin is not None

    def check(self, actor: Actor, pin: str) -> bool:
        """True when no PIN is set or `pin` matches it."""
        require_admin(actor)
        doc = self._db.get(COLLECTION, DOC_ID) or {}
        stored, salt = doc.get("pin_hash"), doc.get("pin_salt")
        if not stored or not salt:
            return True
        with self._lock:
            wait = self._blocked_until - time.monotonic()
            if wait > 0:
                raise ConflictError(
                    f"Слишком много попыток. Подождите {int(wait) + 1} с и попробуйте снова."
                )
        ok = hmac.compare_digest(_hash(pin, salt), stored)
        with self._lock:
            if ok:
                self._misses = 0
            else:
                self._misses += 1
                if self._misses >= _MAX_MISSES:
                    self._misses = 0
                    self._blocked_until = time.monotonic() + _LOCKOUT_SECONDS
        return ok
