
from __future__ import annotations

from typing import Mapping, Tuple

TABLE: Mapping[str, Tuple[str, str]] = {
    "task_manager_board_public_links_remove": ("task_manager.boards.public_links.remove",
                                 "Revoke public review links so outsiders can no longer open a board: one link, every link of a board, or "
                                 "all. Revoke only; links are made by the owner."),
}
