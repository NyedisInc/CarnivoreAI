
import json

from src.core.byoai import decide
from src.core.byoai.contracts import DecideRequest
from src.core.byoai.native import jev
from src.core.byoai.presets import get_preset

REQUEST = DecideRequest(
    state={"event": "build failed"},
    questions={
        "notify": decide.choice(["now", "later", "never"], "when should this buzz?",
                                {"now": "urgent", "later": "can wait", "never": "noise"}),
        "risk": decide.score(0, 10, "how risky is this?", ["safe", "risky"]),
        "page": decide.yes_no("does the owner need to know?"),
    },
)


def test_one_request_two_targets_one_answer_shape():
    body = jev.build_body(REQUEST)
    assert body["questions"]["notify"] == {"type": "choice", "instructions": "when should this buzz?",
                                           "criteria": {"now": "urgent", "later": "can wait", "never": "noise"}}
    assert body["questions"]["risk"]["criteria"] == ["safe", "risky"]
    assert body["questions"]["page"] == {"type": "noul", "instructions": "does the owner need to know?"}

    chat = decide.chat_request(REQUEST)
    prompt = chat.messages[0].content
    assert "when should this buzz?" in prompt and "now = urgent" in prompt and "safe is the lowest" in prompt
    assert chat.json_schema["properties"]["notify"]["enum"] == ["now", "later", "never"]

    jev_result = jev.parse(REQUEST, {"answers": {
        "notify": {"type": "choice", "choice": "now", "probabilities": {"now": 0.9}},
        "risk": {"type": "score", "score": 1, "legend": {"0": "safe", "1": "risky"}},
        "page": {"type": "noul", "noul": 0.8}}})
    chat_result = decide.parse(json.dumps({"notify": "now", "risk": 10, "page": True}), REQUEST.questions)
    assert set(jev_result.answers) == set(chat_result.answers) == set(REQUEST.questions)
    for name in REQUEST.questions:
        assert type(jev_result.answers[name]["value"]) is type(chat_result.answers[name]["value"])
    assert jev_result.answers["notify"]["value"] == chat_result.answers["notify"]["value"] == "now"
    assert jev_result.answers["risk"]["value"] == chat_result.answers["risk"]["value"] == 10.0
    assert jev_result.answers["page"]["value"] is chat_result.answers["page"]["value"] is True


def test_bedrock_presets_type_model_ids_on_their_own_hosts():
    openai, anth = get_preset("bedrock"), get_preset("bedrock_anthropic")
    assert openai.model_source == anth.model_source == "manual"
    assert "/openai/v1" in openai.base_url and "bedrock-mantle" in anth.base_url
