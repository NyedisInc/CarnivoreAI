
import json

from src.core.session_conversations.prompt_texts import read_prompt_texts

UUID = "2629dba5-1111-4222-8333-444455556666"


def _user(text, **extra):
    return {"type": "user", "message": {"role": "user", "content": text}, **extra}


def test_full_prompts_in_order_without_reply_or_noise(tmp_path):
    proj = tmp_path / "-x"
    proj.mkdir()
    records = [
        _user("same start\n\nfirst ending"),
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "REPLY ONE"}]}},
        _user([{"type": "tool_result", "content": "x"}], toolUseResult={"a": 1}),
        _user("meta", isMeta=True),
        _user("sidechain", isSidechain=True),
        _user("same start\n\nsecond ending"),
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "REPLY TWO"}]}},
    ]
    (proj / f"{UUID}.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")

    got = read_prompt_texts(UUID, "/x", corpus_root=tmp_path)

    assert got == ["same start\n\nfirst ending", "same start\n\nsecond ending"]
    assert not any("REPLY" in p for p in got)


def test_missing_transcript_is_empty(tmp_path):
    assert read_prompt_texts(UUID, "/x", corpus_root=tmp_path) == []
    assert read_prompt_texts(None, "/x", corpus_root=tmp_path) == []
