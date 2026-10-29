
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional
from src.core.sessions import errors as session_errors

DELETE = "delete"
KEEP = "keep"
REPORT = "report"

KIND_ROWS = "rows"
KIND_FILE = "file"
KIND_DIR = "dir"
KIND_ENTRY = "entry"
KIND_LINES = "lines"

SCOPE_SESSION = "session"
SCOPE_PROJECT = "project"

ROLE_KEY = "key"
ROLE_PATH = "path"
ROLE_SECRET = "secret"

MAIN_STORE = "cloude.db"


class InventoryError(Exception):
    pass


class SessionNotFound(InventoryError, session_errors.SessionNotFound):
    pass


class ProjectNotFound(InventoryError, LookupError):
    pass


@dataclass(frozen=True)
class SessionIdentity:

    row_id: int
    session_uuid: str
    tmux_name: Optional[str]
    tmux_epoch: Optional[int]
    title: Optional[str]
    conversation: Optional[str]
    agent_family: Optional[str]
    working_dir: Optional[str]
    host_key: Optional[str]
    lifecycle: Optional[str]
    archived_at: Optional[str]
    app_id: Optional[str] = None
    project_id: Optional[int] = None

    @property
    def display_name(self) -> str:
        return (self.title or "").strip() or (self.tmux_name or "").strip() or self.session_uuid

    @property
    def layout_key(self) -> Optional[str]:
        if not self.tmux_name:
            return None
        return self.tmux_name if self.tmux_epoch is None else f"{self.tmux_name}:{self.tmux_epoch}"

    def as_dict(self) -> Dict[str, Any]:
        return {"row_id": self.row_id, "session_uuid": self.session_uuid, "tmux_name": self.tmux_name,
                "tmux_epoch": self.tmux_epoch, "title": self.title, "display_name": self.display_name,
                "conversation": self.conversation, "agent_family": self.agent_family,
                "working_dir": self.working_dir, "lifecycle": self.lifecycle, "archived_at": self.archived_at}


@dataclass(frozen=True)
class ProjectIdentity:

    project_id: int
    uid: Optional[str]
    name: Optional[str]
    root: str
    raw_path: Optional[str]
    company_id: Optional[int]
    archived_at: Optional[str]

    @property
    def list_key(self) -> str:
        return str(self.project_id)

    def as_dict(self) -> Dict[str, Any]:
        return {"project_id": self.project_id, "uid": self.uid, "name": self.name, "root": self.root,
                "company_id": self.company_id, "archived_at": self.archived_at}


@dataclass(frozen=True)
class FieldRef:

    name: str
    role: str

    def as_dict(self) -> Dict[str, str]:
        return {"name": self.name, "role": self.role}


@dataclass
class Artifact:

    store: str
    kind: str
    what: str
    count: int
    action: str = DELETE
    size: int = 0
    reason: str = ""
    locator: Dict[str, Any] = field(default_factory=dict)
    rewrite: List[FieldRef] = field(default_factory=list)
    derived: bool = False
    op: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def table(self) -> str:
        return self.what.split(" ", 1)[0]

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"store": self.store, "kind": self.kind, "what": self.what, "count": self.count,
                               "size": self.size, "action": self.action}
        if self.reason:
            out["reason"] = self.reason
        return out

    def as_inventory_dict(self) -> Dict[str, Any]:
        return {**self.as_dict(), "locator": dict(self.locator), "derived": self.derived,
                "rewrite": [f.as_dict() for f in self.rewrite]}

    def material(self) -> List[Any]:
        return [self.store, self.kind, self.what, self.count, self.size, self.action]


@dataclass
class Inventory:

    scope: str
    session: Optional[SessionIdentity] = None
    project: Optional[ProjectIdentity] = None
    artifacts: List[Artifact] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    children: List["Inventory"] = field(default_factory=list)
    outside: List[str] = field(default_factory=list)
    shared_with: List[Dict[str, Any]] = field(default_factory=list)
    conversations: List[str] = field(default_factory=list)
    home_project: Optional[ProjectIdentity] = None

    def all_artifacts(self) -> Iterator[Artifact]:
        yield from self.artifacts
        for child in self.children:
            yield from child.all_artifacts()

    def find(self, store: str, what: str) -> List[Artifact]:
        return [a for a in self.all_artifacts() if a.store == store and (a.what == what or a.what.startswith(what + " "))]

    def as_dict(self) -> Dict[str, Any]:
        subject = self.session.as_dict() if self.session else (self.project.as_dict() if self.project else {})
        return {"scope": self.scope, "subject": subject, "blockers": list(self.blockers),
                "outside": list(self.outside), "artifacts": [a.as_inventory_dict() for a in self.artifacts],
                "children": [c.as_dict() for c in self.children]}

