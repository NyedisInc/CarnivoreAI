
from __future__ import annotations

from typing import List, Optional

from .catalog_doc import _Doc


class GradeRule(_Doc):

    rule: Optional[str] = None
    level: Optional[str] = None
    detail: Optional[str] = None


class GradeBlock(_Doc):

    grade: Optional[str] = None
    checked: Optional[int] = None
    failed: Optional[List[GradeRule]] = None
    not_graded: Optional[List[str]] = None
