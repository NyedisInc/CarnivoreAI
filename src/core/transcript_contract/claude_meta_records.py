
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from src.core.transcript_contract.fields import BOOL, INT, NUM, OBJ, STR, jf


@dataclass(frozen=True, kw_only=True)
class AgentNameRecord:

    agent_name: Optional[str] = jf("agentName", STR, required=True, first_seen="2.1.121")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.121")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.121")


@dataclass(frozen=True, kw_only=True)
class AiTitleRecord:

    ai_title: Optional[str] = jf("aiTitle", STR, required=True, first_seen="2.1.111")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.111")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.111")


@dataclass(frozen=True, kw_only=True)
class ArtifactAutoreactLedgerRecord:

    account_uuid: Optional[str] = jf("accountUuid", STR, required=True, first_seen="2.1.246")
    artifacts: Optional[Mapping[str, Any]] = jf(
        "artifacts", OBJ, required=True, first_seen="2.1.246")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.246")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.246")
    v: Optional[int] = jf("v", INT, required=True, first_seen="2.1.246")


@dataclass(frozen=True, kw_only=True)
class ArtifactCommentMonitorRecord:

    artifacts: Optional[Mapping[str, Any]] = jf(
        "artifacts", OBJ, required=True, first_seen="2.1.246")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.246")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.246")
    v: Optional[int] = jf("v", INT, required=True, first_seen="2.1.246")


@dataclass(frozen=True, kw_only=True)
class AtisLatchRecord:

    atis: Optional[str] = jf("atis", STR, required=True, first_seen="2.1.111")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.111")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.111")


@dataclass(frozen=True, kw_only=True)
class BridgeSessionRecord:

    bridge_session_id: Optional[str] = jf(
        "bridgeSessionId", STR, required=True, first_seen="2.1.111")
    last_sequence_num: Optional[int] = jf(
        "lastSequenceNum", INT, required=True, first_seen="2.1.111")
    no_history_backfill: Optional[bool] = jf("noHistoryBackfill", BOOL, first_seen="2.1.284")
    owner_account_uuid: Optional[str] = jf("ownerAccountUuid", STR, first_seen="2.1.111")
    owner_organization_uuid: Optional[str] = jf("ownerOrganizationUuid", STR, first_seen="2.1.111")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.111")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.111")


@dataclass(frozen=True, kw_only=True)
class CostStateRecord:

    has_unknown_model_cost: Optional[bool] = jf(
        "hasUnknownModelCost", BOOL, required=True, first_seen="2.1.128")
    model_usage: Optional[Mapping[str, Any]] = jf(
        "modelUsage", OBJ, required=True, first_seen="2.1.128")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.128")
    start_time: Optional[int] = jf("startTime", INT, required=True, first_seen="2.1.128")
    total_apiduration: Optional[int] = jf(
        "totalAPIDuration", INT, required=True, first_seen="2.1.128")
    total_apiduration_without_retries: Optional[int] = jf(
        "totalAPIDurationWithoutRetries", INT, required=True, first_seen="2.1.128")
    total_cost_usd: Optional[float] = jf(
        "totalCostUSD", INT + NUM, required=True, first_seen="2.1.128")
    total_duration: Optional[int] = jf("totalDuration", INT, required=True, first_seen="2.1.128")
    total_lines_added: Optional[int] = jf(
        "totalLinesAdded", INT, required=True, first_seen="2.1.128")
    total_lines_removed: Optional[int] = jf(
        "totalLinesRemoved", INT, required=True, first_seen="2.1.128")
    total_tool_duration: Optional[int] = jf(
        "totalToolDuration", INT, required=True, first_seen="2.1.128")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.128")


@dataclass(frozen=True, kw_only=True)
class CustomTitleRecord:

    custom_title: Optional[str] = jf("customTitle", STR, required=True, first_seen="2.0.76")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.0.76")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.0.76")


@dataclass(frozen=True, kw_only=True)
class FileHistoryDeltaRecord:

    backup: Optional[Mapping[str, Any]] = jf("backup", OBJ, required=True, first_seen="2.1.251")
    message_id: Optional[str] = jf("messageId", STR, required=True, first_seen="2.1.251")
    snapshot_message_id: Optional[str] = jf(
        "snapshotMessageId", STR, required=True, first_seen="2.1.251")
    timestamp: Optional[str] = jf("timestamp", STR, required=True, first_seen="2.1.251")
    tracking_path: Optional[str] = jf("trackingPath", STR, required=True, first_seen="2.1.251")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.251")


@dataclass(frozen=True, kw_only=True)
class FileHistorySnapshotRecord:

    is_snapshot_update: Optional[bool] = jf(
        "isSnapshotUpdate", BOOL, required=True, first_seen="2.0.1")
    message_id: Optional[str] = jf("messageId", STR, required=True, first_seen="2.0.1")
    snapshot: Optional[Mapping[str, Any]] = jf("snapshot", OBJ, required=True, first_seen="2.0.1")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.0.1")


@dataclass(frozen=True, kw_only=True)
class ForkContextRefRecord:

    agent_id: Optional[str] = jf("agentId", STR, required=True)
    context_length: Optional[int] = jf("contextLength", INT, required=True)
    parent_last_uuid: Optional[str] = jf("parentLastUuid", STR, required=True)
    parent_session_id: Optional[str] = jf("parentSessionId", STR, required=True)
    type: Optional[str] = jf("type", STR, required=True)


@dataclass(frozen=True, kw_only=True)
class FrameLinkRecord:

    artifact_count: Optional[int] = jf("artifactCount", INT, required=True, first_seen="2.1.246")
    frame_url: Optional[str] = jf("frameUrl", STR, first_seen="2.1.246")
    path: Optional[str] = jf("path", STR, first_seen="2.1.246")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.246")
    timestamp: Optional[str] = jf("timestamp", STR, required=True, first_seen="2.1.246")
    title: Optional[str] = jf("title", STR, first_seen="2.1.246")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.246")


@dataclass(frozen=True, kw_only=True)
class HistorySuppressionRecord:

    cause: Optional[str] = jf("cause", STR, required=True, first_seen="2.1.284")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.284")
    ts: Optional[str] = jf("ts", STR, required=True, first_seen="2.1.284")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.284")
    vetoed_against_account_uuid: Optional[str] = jf(
        "vetoedAgainstAccountUuid", STR, first_seen="2.1.284")


@dataclass(frozen=True, kw_only=True)
class LastPromptRecord:

    last_prompt: Optional[str] = jf("lastPrompt", STR, first_seen="2.1.71")
    leaf_uuid: Optional[str] = jf("leafUuid", STR, first_seen="2.1.121")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.71")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.71")


@dataclass(frozen=True, kw_only=True)
class ModeRecord:

    mode: Optional[str] = jf("mode", STR, required=True, first_seen="2.1.111")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.111")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.111")


@dataclass(frozen=True, kw_only=True)
class PermissionModeRecord:

    permission_mode: Optional[str] = jf("permissionMode", STR, required=True, first_seen="2.1.128")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.128")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.128")


@dataclass(frozen=True, kw_only=True)
class PrLinkRecord:

    pr_number: Optional[int] = jf("prNumber", INT, required=True, first_seen="2.1.160")
    pr_repository: Optional[str] = jf("prRepository", STR, required=True, first_seen="2.1.160")
    pr_url: Optional[str] = jf("prUrl", STR, required=True, first_seen="2.1.160")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.1.160")
    timestamp: Optional[str] = jf("timestamp", STR, required=True, first_seen="2.1.160")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.1.160")


@dataclass(frozen=True, kw_only=True)
class QueueOperationRecord:

    command_uuid: Optional[str] = jf("commandUuid", STR, first_seen="2.1.285")
    content: Optional[str] = jf("content", STR, first_seen="2.0.64")
    delivery_id: Optional[str] = jf("deliveryId", STR, first_seen="2.1.286")
    operation: Optional[str] = jf("operation", STR, required=True, first_seen="2.0.64")
    reason: Optional[str] = jf("reason", STR, first_seen="2.1.246")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="2.0.64")
    timestamp: Optional[str] = jf("timestamp", STR, required=True, first_seen="2.0.64")
    type: Optional[str] = jf("type", STR, required=True, first_seen="2.0.64")


@dataclass(frozen=True, kw_only=True)
class SummaryRecord:

    leaf_uuid: Optional[str] = jf("leafUuid", STR, required=True, first_seen="1.0.63")
    summary: Optional[str] = jf("summary", STR, required=True, first_seen="1.0.63")
    type: Optional[str] = jf("type", STR, required=True, first_seen="1.0.63")


@dataclass(frozen=True, kw_only=True)
class WorkflowStartedRecord:

    agent_id: Optional[str] = jf("agentId", STR, required=True)
    key: Optional[str] = jf("key", STR, required=True)
    type: Optional[str] = jf("type", STR, required=True)


@dataclass(frozen=True, kw_only=True)
class WorkflowResultRecord:

    agent_id: Optional[str] = jf("agentId", STR, required=True)
    key: Optional[str] = jf("key", STR, required=True)
    result: Optional[Mapping[str, Any] | str] = jf("result", OBJ + STR, required=True)
    type: Optional[str] = jf("type", STR, required=True)


