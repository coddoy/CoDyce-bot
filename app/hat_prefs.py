"""Persistent per-user hat die preferences for Discord slash-command rollers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PREFS_FILENAME = "hat_user_prefs.json"


def default_prefs_path(config_path: str | Path) -> Path:
    """Return the prefs file path alongside a config JSON file."""
    return Path(config_path).resolve().parent / DEFAULT_PREFS_FILENAME


@dataclass
class _UserEntry:
    die: int
    display_name: str


class HatUserPrefsStore:
    """Load/save per-Discord-user hat shorthand die overrides."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._users: dict[str, _UserEntry] = {}

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        """Read prefs from disk. Missing or corrupt files start empty."""
        if not self._path.exists():
            self._users = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not load hat prefs from %s: %s", self._path, exc)
            self._users = {}
            return

        users_raw = raw.get("users", {}) or {}
        loaded: dict[str, _UserEntry] = {}
        for key, entry in users_raw.items():
            if not isinstance(entry, dict):
                continue
            try:
                die = int(entry["die"])
                name = str(entry.get("display_name", key))
            except (KeyError, TypeError, ValueError):
                continue
            loaded[str(key)] = _UserEntry(die=die, display_name=name)
        self._users = loaded
        log.info(
            "Loaded %d hat die override(s) from %s",
            len(self._users),
            self._path,
        )

    def save(self) -> None:
        """Persist prefs atomically."""
        payload = {
            "users": {
                uid: {
                    "die": entry.die,
                    "display_name": entry.display_name,
                }
                for uid, entry in self._users.items()
            }
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def get_die(self, user_id: int) -> int | None:
        """Return the user's stored override, or ``None`` when unset."""
        entry = self._users.get(str(user_id))
        return entry.die if entry else None

    def effective_die(self, user_id: int, default: int) -> int:
        """Die used for hat shorthand when the user has no override."""
        return self.get_die(user_id) or default

    def set_die(self, user_id: int, die: int, display_name: str) -> None:
        self._users[str(user_id)] = _UserEntry(
            die=die,
            display_name=display_name,
        )

    def list_overrides(self) -> list[tuple[str, int]]:
        """Return ``(display_name, die)`` pairs sorted by name."""
        entries = [
            (entry.display_name, entry.die) for entry in self._users.values()
        ]
        return sorted(entries, key=lambda pair: pair[0].casefold())

    def touch_display_name(self, user_id: int, display_name: str) -> None:
        """Update a stored display name in memory when the user rolls."""
        key = str(user_id)
        entry = self._users.get(key)
        if entry is not None and entry.display_name != display_name:
            self._users[key] = _UserEntry(die=entry.die, display_name=display_name)


__all__ = [
    "DEFAULT_PREFS_FILENAME",
    "HatUserPrefsStore",
    "default_prefs_path",
]
