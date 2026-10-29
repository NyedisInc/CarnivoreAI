
from src.core.swarm.stream_sources import SUMMARY_CHARS, summary_line, traffic_entry


def _msg(text: str) -> dict:
    return {"id": 4, "created_at": 9.0, "sender_key": "u-boss", "receiver_key": "u-lead", "receiver_name": "Orchardco",
            "receiver_id": "ses_x", "sender_name": "Nyedis", "text": text, "thread": "t-1", "in_reply_to": None,
            "status": "delivered", "reason": None, "delivered_at": 10.0}


def test_the_summary_is_the_first_meaningful_line_without_markup():
    assert summary_line("\n\n## Owner order\n\nrename the page") == "Owner order"
    assert summary_line("> - **ship** it\nmore") == "ship it"
    assert summary_line("---\n1. `copy` the file") == "copy the file"
    assert summary_line("") == "" and summary_line("\n  \n") == ""


def test_a_long_line_is_cut_at_a_word_on_one_line():
    line = summary_line("word " * 60)
    assert len(line) <= SUMMARY_CHARS and line.endswith("...") and "\n" not in line
    assert not line[:-3].endswith(" ")


def test_every_traffic_entry_carries_the_summary_beside_the_full_text():
    text = "Owner order: rename the NHI flow page.\n\nDo:\n1. copy it"
    entry = traffic_entry("u-boss", _msg(text))
    assert entry["summary"] == "Owner order: rename the NHI flow page."
    assert entry["text"] == text
