"""Accounts, sessions and per-student attempt history.

A small, honest local store: users in a JSON file, passwords hashed with scrypt
and a per-user salt, sessions as opaque tokens held in memory.

This is sized for a local single-machine deployment. It is deliberately *not* a
production auth system — no email verification, no rate limiting, no password
reset, no CSRF tokens. Swap it for a real identity provider before this faces
the internet; ``AccountStore`` is the seam to replace.

Attempt history lives here too, because Steps 11 and 12 (weak-area detection and
readiness estimation) need performance across *several* tests, which means it has
to outlive a single page load.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .errors import ValidationError

#: scrypt parameters. n=2**14 keeps a login well under a second on a laptop
#: while staying far above a plain hash in cost.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DK_LEN = 64

SESSION_TTL_SECONDS = 12 * 3600
MIN_PASSWORD_LENGTH = 8
MAX_ATTEMPTS_KEPT = 60

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def default_data_dir() -> Path:
    """Where user data lives. Overridable for tests and deployments."""
    override = os.environ.get("AIPARIKSHA_DATA_DIR")
    if override:
        return Path(override)
    return Path.cwd() / ".aipariksha_data"


@dataclass(slots=True)
class User:
    user_id: str
    name: str
    email: str
    password_hash: str
    salt: str
    target_exam: str = ""
    created_at: float = 0.0
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        """Everything safe to send to the client. Never the hash or salt."""
        return {
            "user_id": self.user_id,
            "name": self.name,
            "email": self.email,
            "target_exam": self.target_exam,
            "attempt_count": len(self.attempts),
        }

    def to_record(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "email": self.email,
            "password_hash": self.password_hash,
            "salt": self.salt,
            "target_exam": self.target_exam,
            "created_at": self.created_at,
            "attempts": self.attempts,
        }

    @classmethod
    def from_record(cls, raw: Mapping[str, Any]) -> "User":
        return cls(
            user_id=str(raw.get("user_id") or ""),
            name=str(raw.get("name") or ""),
            email=str(raw.get("email") or "").lower(),
            password_hash=str(raw.get("password_hash") or ""),
            salt=str(raw.get("salt") or ""),
            target_exam=str(raw.get("target_exam") or ""),
            created_at=float(raw.get("created_at") or 0.0),
            attempts=list(raw.get("attempts") or []),
        )


class AccountStore:
    """Thread-safe JSON-backed user store."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._dir = Path(data_dir) if data_dir else default_data_dir()
        self._path = self._dir / "users.json"
        self._lock = threading.RLock()
        self._users: dict[str, User] = {}
        self._sessions: dict[str, tuple[str, float]] = {}
        self._load()

    # ----------------------------------------------------------------- storage

    def _load(self) -> None:
        with self._lock:
            if not self._path.is_file():
                return
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                # A corrupt store must not take the whole app down; start empty
                # and leave the bad file in place for inspection.
                return
            for record in raw.get("users", []):
                user = User.from_record(record)
                if user.email:
                    self._users[user.email] = user

    def _save(self) -> None:
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            payload = {"users": [u.to_record() for u in self._users.values()]}
            # Write-then-replace so an interrupted save cannot truncate the file.
            temp = self._path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp.replace(self._path)

    # -------------------------------------------------------------------- auth

    def register(
        self, name: str, email: str, password: str, target_exam: str = ""
    ) -> tuple[User, str]:
        name = str(name or "").strip()
        email = str(email or "").strip().lower()
        password = str(password or "")

        if not name:
            raise ValidationError("Please enter your name.", field="name")
        if not _EMAIL_RE.match(email):
            raise ValidationError("Please enter a valid email address.", field="email")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", field="password"
            )

        with self._lock:
            if email in self._users:
                raise ValidationError(
                    "An account already exists for that email. Sign in instead.", field="email"
                )
            salt = secrets.token_hex(16)
            user = User(
                user_id=secrets.token_hex(8),
                name=name,
                email=email,
                password_hash=_hash_password(password, salt),
                salt=salt,
                target_exam=str(target_exam or ""),
                created_at=time.time(),
            )
            self._users[email] = user
            self._save()
            return user, self._new_session(email)

    def login(self, email: str, password: str) -> tuple[User, str]:
        email = str(email or "").strip().lower()
        password = str(password or "")

        with self._lock:
            user = self._users.get(email)
            # Same message either way: do not reveal which accounts exist.
            failure = ValidationError("Email or password is incorrect.", field="password")
            if user is None:
                # Spend comparable time so timing does not leak account existence.
                _hash_password(password, "0" * 32)
                raise failure
            if not hmac.compare_digest(
                user.password_hash, _hash_password(password, user.salt)
            ):
                raise failure
            return user, self._new_session(email)

    def _new_session(self, email: str) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = (email, time.time() + SESSION_TTL_SECONDS)
        return token

    def user_for_token(self, token: str | None) -> User | None:
        if not token:
            return None
        with self._lock:
            entry = self._sessions.get(token)
            if entry is None:
                return None
            email, expires = entry
            if time.time() > expires:
                self._sessions.pop(token, None)
                return None
            return self._users.get(email)

    def logout(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._sessions.pop(token, None)

    # ----------------------------------------------------------------- history

    def record_attempt(self, user: User, entry: Mapping[str, Any]) -> None:
        """Append one completed attempt to a student's history."""
        with self._lock:
            user.attempts.append(dict(entry))
            if len(user.attempts) > MAX_ATTEMPTS_KEPT:
                del user.attempts[: len(user.attempts) - MAX_ATTEMPTS_KEPT]
            self._save()

    def history_payload(self, user: User) -> dict[str, Any]:
        """History in the shape ``StudentHistory.from_dict`` expects."""
        with self._lock:
            return {"student_id": user.user_id, "attempts": list(user.attempts)}

    def set_target_exam(self, user: User, exam: str) -> None:
        with self._lock:
            user.target_exam = str(exam or "")
            self._save()

    def clear_history(self, user: User) -> None:
        with self._lock:
            user.attempts.clear()
            self._save()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DK_LEN,
    ).hex()
