
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.lineage import constants as K
from src.core.lineage import graph, milestones

logger = structlog.get_logger()

CUT_WRITTEN = "written"
CUT_NO_SCHEMA = "no_schema"


def split_detail(source_conversation: str, entry_uuid: Optional[str], via: str) -> Dict[str, Any]:
    values = ((K.DETAIL_SPLIT_SESSION, source_conversation), (K.DETAIL_SPLIT_MESSAGE, entry_uuid),
              (K.DETAIL_VIA, via), (K.DETAIL_EVIDENCE, K.EVIDENCE_ROUTE))
    return {k: v for k, v in values if v is not None}


def record_cut(db_path: Path, *, kind: str, source_conversation: str, copy_conversation: str,
               session_uuid: Optional[str], entry_uuid: Optional[str] = None, via: str) -> str:
    from src.core.db import connect, transaction

    detail = split_detail(source_conversation, entry_uuid, via)
    with closing(connect(db_path, create=False)) as conn:
        if not graph.ready(conn):
            logger.info("lineage_cut_skipped", reason="datastore before schema v49", kind=kind)
            return CUT_NO_SCHEMA
        with transaction(conn):
            graph.add_edge(conn, K.NODE_CONVERSATION, source_conversation, K.NODE_CONVERSATION, copy_conversation,
                           kind, detail=detail)
            if session_uuid:
                graph.add_edge(conn, K.NODE_CONVERSATION, source_conversation, K.NODE_SESSION, session_uuid, kind,
                               detail=detail)
            known = [m for m in milestones.milestones_of(conn, source_conversation)
                     if m["kind"] == kind and m["detail"].get("copy_conversation_id") == copy_conversation]
            if not known:
                milestones.add_milestone(
                    conn, source_conversation, kind, K.SOURCE_PIPELINE, session_uuid=session_uuid,
                    detail={"copy_conversation_id": copy_conversation, **detail})
    logger.info("lineage_cut_recorded", kind=kind, source=source_conversation, copy=copy_conversation,
                session_uuid=session_uuid, entry=entry_uuid)
    return CUT_WRITTEN
