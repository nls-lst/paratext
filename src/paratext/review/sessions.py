"""Per-attendee workspaces for workshop mode.

A Space is one container shared by everyone looking at it, so without this a
room full of people editing one prompt overwrite each other. Each browser gets
a session: its own prompt and fields, its own rounds, its own verdicts.

Sessions are disposable. They live under a root the caller chooses (``/tmp`` in
a Space), and losing them costs a workshop exercise, not data.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..store import Store

# A session id comes back from a cookie, i.e. from the client. It is used to
# build a path, so it is matched against this and rejected otherwise — never
# sanitised and used anyway.
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
COOKIE_NAME = "pt_session"


def new_session_id() -> str:
    return secrets.token_urlsafe(18)


def valid_session_id(sid: str | None) -> bool:
    return bool(sid and SESSION_ID.match(sid))


@dataclass
class Session:
    id: str
    dir: Path

    @property
    def data_dir(self) -> Path:
        """Where this attendee's rounds live — the review root for them."""
        return self.dir / "review"

    @property
    def db_path(self) -> Path:
        return self.dir / "annotations.db"

    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    def store(self) -> Store:
        return Store(self.db_path)

    def read_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def write_state(self, state: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=1))


class Sessions:
    """Creates and finds session workspaces under one root."""

    def __init__(self, root: Path, examples: list[Path] | None = None):
        self.root = Path(root)
        self.examples = list(examples or [])

    def path_for(self, sid: str) -> Path:
        return self.root / sid

    def exists(self, sid: str) -> bool:
        return valid_session_id(sid) and self.path_for(sid).is_dir()

    def get(self, sid: str | None) -> Session | None:
        if not valid_session_id(sid) or not self.path_for(sid).is_dir():
            return None
        return Session(id=sid, dir=self.path_for(sid))

    def create(self, sid: str | None = None) -> Session:
        sid = sid if valid_session_id(sid) else new_session_id()
        session = Session(id=sid, dir=self.path_for(sid))
        session.data_dir.mkdir(parents=True, exist_ok=True)
        self._seed_examples(session)
        return session

    def get_or_create(self, sid: str | None) -> tuple[Session, bool]:
        """Returns the session and whether it was just created (so the caller
        knows to set the cookie)."""
        found = self.get(sid)
        if found:
            return found, False
        return self.create(), True

    def _seed_examples(self, session: Session) -> None:
        """Symlink the shipped rounds in, so every attendee starts with the same
        worked example beside their own work. Symlinked, not copied: the rounds
        are read-only and their images are the bulk of the image."""
        for src in self.examples:
            dest = session.data_dir / src.name
            if dest.exists() or not src.is_dir():
                continue
            try:
                dest.symlink_to(src.resolve(), target_is_directory=True)
            except OSError:
                shutil.copytree(src, dest)

    def reset(self, sid: str) -> bool:
        """Delete one session's workspace. Used by the facilitator reset."""
        if not self.exists(sid):
            return False
        shutil.rmtree(self.path_for(sid))
        return True

    def all_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())
