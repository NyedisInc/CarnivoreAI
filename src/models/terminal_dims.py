
from __future__ import annotations

from typing import Annotated

from pydantic import Field

MIN_COLS: int = 10
MIN_ROWS: int = 5
MAX_CELLS: int = 1000

TermCols = Annotated[int, Field(ge=MIN_COLS, le=MAX_CELLS)]
TermRows = Annotated[int, Field(ge=MIN_ROWS, le=MAX_CELLS)]
