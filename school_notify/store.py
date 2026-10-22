"""config.json (credentials + choices, written by setup) and state.json (what was already seen)."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_OPTIONS = {
    "poll_minutes": 30,
    "quiet_hours": None,  # e.g. "22:00-07:00": notifications wait until it ends
    "webtop": {"homework": True, "messages": True, "message_bodies": False, "lesson_events": True, "attendance": True},
    "galim": {"new_tasks": True, "grades": True},
    "alert_after_hours": 12,  # tell the parent when a source keeps failing this long
}


def data_dir(arg=None):
    path = Path(arg or os.environ.get("SCHOOL_NOTIFY_DATA") or Path(__file__).resolve().parent.parent / "data")
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    # Created private: config.json holds the Galim password and the Webtop credential.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def merged_options(cfg):
    opts = json.loads(json.dumps(DEFAULT_OPTIONS))
    for key, value in (cfg.get("options") or {}).items():
        if isinstance(value, dict) and isinstance(opts.get(key), dict):
            opts[key].update(value)
        else:
            opts[key] = value
    return opts


class Store:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.config_path = self.dir / "config.json"
        self.state_path = self.dir / "state.json"
        self.config = _read(self.config_path)
        self.state = _read(self.state_path)
        # Env vars win, for Docker / secret managers.
        if os.environ.get("GALIM_USERNAME") and os.environ.get("GALIM_PASSWORD"):
            self.config["galim"] = {"username": os.environ["GALIM_USERNAME"], "password": os.environ["GALIM_PASSWORD"]}

    @property
    def options(self):
        return merged_options(self.config)

    def save_config(self):
        _write(self.config_path, self.config)

    def save_state(self):
        _write(self.state_path, self.state)

    def lock(self):
        """Exclusive lock so a manual `poll` and the running service never overlap."""
        fh = open(self.dir / ".lock", "w")
        try:
            import fcntl

            fcntl.flock(fh, fcntl.LOCK_EX)
        except ImportError:  # Windows: no flock; the service is the only writer there anyway
            pass
        return fh
