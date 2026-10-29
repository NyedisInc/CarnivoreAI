
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

GitState = Literal["ok", "not_a_repo", "unknown", "remote"]
GitFileKind = Literal["modified", "added", "deleted", "renamed", "copied", "typechange", "untracked", "conflicted"]


class GitFile(BaseModel):

    path: str
    orig_path: Optional[str] = Field(default=None, description="the old path of a rename or copy")
    index: str = Field(default=".", description="staged side code, '.' none, '?' untracked")
    worktree: str = Field(default=".", description="unstaged side code, '.' none, '?' untracked")
    kind: GitFileKind
    submodule: bool = Field(default=False, description="a submodule is one flagged row, never expanded")


class GitCounts(BaseModel):
    """Totals over EVERY changed path, including those cut from ``files`` by the cap."""

    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    conflicted: int = 0


class SessionGitStatus(BaseModel):
    """What ``git status`` says about a directory; ``unknown`` (timeout or any error) is never shown as clean.

    ``remote`` is the route's answer for a paired-computer session: git is never read for it here.
    """

    state: GitState
    repo_root: Optional[str] = None
    working_dir_real: Optional[str] = Field(
        default=None,
        description="the session's stored folder with symlinks resolved, for mapping listed paths onto its tree",
    )
    repo_name: Optional[str] = Field(default=None, description="basename of the work tree's top level")
    branch: Optional[str] = Field(default=None, description="None when detached or on an unborn branch with no name")
    detached: bool = False
    head_short: Optional[str] = Field(default=None, description="short sha of HEAD; None on an unborn branch")
    unborn: bool = Field(default=False, description="the branch has no commits yet")
    upstream: Optional[str] = None
    remote: Optional[str] = None
    ahead: Optional[int] = Field(default=None, description="None when there is no upstream")
    behind: Optional[int] = None
    counts: GitCounts = Field(default_factory=GitCounts)
    files: List[GitFile] = Field(default_factory=list)
    truncated: int = Field(default=0, description="how many changed paths were cut past the file cap")
    read_at: Optional[float] = Field(default=None, description="epoch seconds the read finished")


DiffState = Literal["ok", "unknown", "remote"]


class SessionGitDiff(BaseModel):
    """One file's read-only diff against HEAD (#148). ``unknown`` (git failed or timed out) is never an empty diff.

    ``binary``, ``sensitive`` and ``directory`` answer the path's name only: ``text`` stays empty and the flag says why.
    """

    state: DiffState
    path: Optional[str] = None
    text: str = Field(default="", description="unified diff, cut at the byte cap")
    truncated: bool = Field(default=False, description="the diff was longer than the cap")
    untracked: bool = Field(default=False, description="text is the file's content shown as an all-added diff")
    binary: bool = False
    sensitive: bool = Field(default=False, description="a secret-looking file name: never read")
    directory: bool = Field(default=False, description="an untracked folder row: no single file to diff")
