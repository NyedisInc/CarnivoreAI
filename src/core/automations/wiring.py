from __future__ import annotations

from pathlib import Path

import structlog

from src.config.byoai import TargetRef
from src.core.automations import targets
from src.core.automations.scrooge import ai_pass
from src.core.automations.targets import agent, blueprint, card, command, recipe, sequence, session_message
from src.core.byoai import gateway as gateway_module
from src.core.byoai import registry
from src.core.byoai.contracts import CAP_AGENT, ByoaiError

logger = structlog.get_logger()
SEED_MARKER = "scrooge_route_seeded"
MODEL = "sonnet"
CLI_PRESET = "claude_cli"


def register_feature() -> None:
    if registry.get_feature(ai_pass.FEATURE_ID) is None:
        registry.register_feature(ai_pass.FEATURE_ID, CAP_AGENT, ai_pass.FEATURE_LABEL_KEY, ai_pass.FEATURE_DESCRIPTION_KEY,
                                  group=ai_pass.FEATURE_GROUP)


def seed_route(state_dir: Path) -> bool:
    marker = state_dir / "automations" / SEED_MARKER
    if marker.exists():
        return False
    store = gateway_module.get_gateway().store
    block = store.read()
    written = False
    if ai_pass.FEATURE_ID not in block.features:
        cli = next((c for c in block.connections if c.preset == CLI_PRESET and c.enabled), None)
        if cli is None:
            return False
        try:
            store.set_feature(ai_pass.FEATURE_ID, TargetRef(connection=cli.id, model=MODEL))
            written = True
        except ByoaiError as exc:
            logger.warning("scrooge_route_seed_failed", error_type=type(exc).__name__)
            return False
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("1")
    return written


def register(state_dir: Path) -> None:
    register_feature()
    seed_route(state_dir)
    targets.RUNNERS["recipe"] = recipe.run
    targets.RUNNERS["agent"] = agent.run
    targets.VALIDATORS["agent"] = agent.validate_target
    targets.RUNNERS["blueprint_launch"] = blueprint.run
    targets.VALIDATORS["blueprint_launch"] = blueprint.validate_target
    targets.RUNNERS["swarm_card"] = card.run
    targets.VALIDATORS["swarm_card"] = card.validate_target
    targets.RUNNERS["session_message"] = session_message.run
    targets.VALIDATORS["session_message"] = session_message.validate_target
    targets.LOGIN_HINTS["session_message"] = session_message.login_hint
    targets.RUNNERS["command"] = command.run
    targets.VALIDATORS["command"] = command.validate_target
    targets.RUNNERS["sequence"] = sequence.run
    targets.VALIDATORS["sequence"] = sequence.validate_target
    targets.LOGIN_HINTS["sequence"] = sequence.login_hint
