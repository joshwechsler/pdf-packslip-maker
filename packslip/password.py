"""The Settings password: stored as a salted hash in settings.json, never as the password itself."""

from __future__ import annotations

import hashlib
import hmac
import os

_ROUNDS = 200_000


def _hash(pw: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _ROUNDS).hex()


def is_set(settings: dict) -> bool:
    return bool((settings.get("settings_password") or {}).get("hash"))


def set_password(settings: dict, pw: str) -> None:
    """Set (or, with an empty password, remove) the Settings password."""
    if not pw:
        settings.pop("settings_password", None)
        return
    salt = os.urandom(16)
    settings["settings_password"] = {"salt": salt.hex(), "hash": _hash(pw, salt)}


def check(settings: dict, pw: str) -> bool:
    """True if pw is right, or if no password has been set."""
    saved = settings.get("settings_password") or {}
    if not saved.get("hash"):
        return True
    try:
        salt = bytes.fromhex(saved.get("salt", ""))
    except ValueError:
        return False
    return hmac.compare_digest(_hash(pw or "", salt), saved["hash"])
