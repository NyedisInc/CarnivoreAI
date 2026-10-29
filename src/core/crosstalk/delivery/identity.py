
from src.models import SessionInfo


def conversation_id(info: SessionInfo, message: dict) -> str | None:
    if (info.session.id != message['receiver_id']
            or info.session.tmux_created_epoch != message['receiver_epoch']):
        return None
    return info.claude_session_uuid
