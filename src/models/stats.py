from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Metric = Literal[
    "input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens",
    "total_tokens", "estimated_cost_nano_usd", "usage_count",
    "observed_seconds", "working_seconds", "running_seconds",
    "starts", "completions", "average_working_agents", "average_running_agents",
    "quota_utilization", "waiting_seconds", "subagent_seconds",
    "tool_calls", "stop_reasons", "thinking_tokens", "web_searches", "web_fetches",
    "compactions", "turns", "cache_write_5m_tokens", "cache_write_1h_tokens",
]
Dimension = Literal["host", "provider", "project", "model", "agent_kind", "conversation_id", "account_id", "window", "subagent_type", "key"]
Resolution = Literal["auto", "minute", "5minute", "hour", "day", "week", "month", "year"]


RollingPreset = Literal["1h", "6h", "24h", "7d", "30d", "90d"]
ROLLING_SECONDS: dict[str, int] = {"1h": 3600, "6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400,
                                   "30d": 30 * 86400, "90d": 90 * 86400}


def _clock() -> float:
    return time.time()


def rolling_window(preset: str, now: float | None = None) -> tuple[datetime, datetime]:
    end = int((_clock() if now is None else now) // 60) * 60 + 60
    return (datetime.fromtimestamp(end - ROLLING_SECONDS[preset], timezone.utc),
            datetime.fromtimestamp(end, timezone.utc))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatsFilters(StrictModel):
    host: str | None = Field(None, max_length=128)
    provider: Literal["claude", "codex"] | None = None
    project: str | None = Field(None, max_length=512)
    model: str | None = Field(None, max_length=128)
    agent_kind: str | None = Field(None, max_length=64)
    conversation_id: str | None = Field(None, max_length=128)
    account_id: str | None = Field(None, max_length=128)
    window: str | None = Field(None, max_length=64)
    subagent_type: str | None = Field(None, max_length=64)

    @field_validator("host", "project", "model", "agent_kind", "conversation_id", "account_id", "window",
                     "subagent_type")
    @classmethod
    def safe_value(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or any(ord(c) < 32 for c in value)):
            raise ValueError("filter must be nonempty and contain no control characters")
        return value


class TimeRange(StrictModel):
    from_: datetime = Field(alias="from")
    to: datetime

    @model_validator(mode="after")
    def valid_range(self):
        if self.from_.tzinfo is None or self.to.tzinfo is None or self.from_ >= self.to:
            raise ValueError("range must be increasing and timezone-aware")
        if (self.to - self.from_).days > 3653:
            raise ValueError("range exceeds ten years")
        return self


class QueryRequest(TimeRange):
    metric: Metric
    operation: Literal["summary", "timeline", "ranking", "comparison"] = "timeline"
    timezone: str = Field("UTC", max_length=64)
    resolution: Resolution = "auto"
    filters: StatsFilters = Field(default_factory=StatsFilters)
    group_by: Dimension | None = None
    top_n: int = Field(5, ge=1, le=10)
    transform: Literal["total", "rate", "cumulative", "per_conversation"] = "total"
    comparison: TimeRange | None = None
    rolling: RollingPreset | None = None
    scope: Literal["local", "pack"] = "local"

    @model_validator(mode="before")
    @classmethod
    def fill_rolling(cls, data):
        if not isinstance(data, dict) or data.get("rolling") not in ROLLING_SECONDS:
            return data
        start, end = rolling_window(data["rolling"])
        data = {**data, "from": start, "to": end}
        if data.get("operation") == "comparison":
            data["comparison"] = {"from": start - (end - start), "to": start}
        return data

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unknown IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def valid_options(self):
        if self.operation == "ranking" and self.group_by is None:
            raise ValueError("ranking requires group_by")
        if self.operation == "comparison" and self.comparison is None:
            raise ValueError("comparison requires comparison range")
        if self.comparison is not None and self.operation != "comparison":
            raise ValueError("comparison range requires comparison operation")
        if self.metric == "quota_utilization" and self.group_by not in (None, "account_id", "window", "provider"):
            raise ValueError("quota only supports account_id, window or provider grouping")
        if self.metric != "quota_utilization" and (self.filters.window or self.group_by == "window"):
            raise ValueError("the window dimension requires quota metric")
        if self.metric == "quota_utilization" and self.transform != "total":
            raise ValueError("quota utilization cannot be transformed")
        if self.metric.startswith("average_") and self.transform != "total":
            raise ValueError("average agent counts cannot be transformed")
        return self


class SettingsPatch(StrictModel):
    enabled: bool
    revision: int = Field(ge=1)


class ChartSeries(StrictModel):
    metric: Metric
    operation: Literal["summary", "timeline", "ranking", "comparison"] = "timeline"
    group_by: Dimension | None = None
    transform: Literal["total", "rate", "cumulative", "per_conversation"] = "total"
    filters: StatsFilters = Field(default_factory=StatsFilters)
    visible: bool = True
    label: str | None = Field(None, max_length=80)

    @model_validator(mode="after")
    def valid_transform(self):
        if self.metric in ("quota_utilization", "average_working_agents",
                           "average_running_agents") and self.transform != "total":
            raise ValueError("metric supports total transform only")
        if self.metric == "quota_utilization" and self.group_by not in (
            None, "account_id", "window", "provider"
        ):
            raise ValueError("quota grouping is unsupported")
        return self


ChartPreset = Literal["1h", "6h", "24h", "7d", "30d", "90d"]


class ChartRange(StrictModel):

    mode: Literal["global", "pinned"] = "global"
    from_: datetime | None = Field(None, alias="from")
    to: datetime | None = None
    preset: ChartPreset | None = None
    zoom: TimeRange | None = None

    @model_validator(mode="after")
    def valid_pinned(self):
        if self.preset is not None and self.mode != "global":
            raise ValueError("a range preset needs global mode")
        if self.mode == "pinned":
            if self.from_ is None or self.to is None:
                raise ValueError("pinned range needs from and to")
            TimeRange.model_validate({"from": self.from_, "to": self.to})
        elif self.from_ is not None or self.to is not None:
            raise ValueError("global range has no pinned timestamps")
        return self


class ChartDisplay(StrictModel):
    type: Literal["line", "area", "bar"] = "line"
    stacked: bool = False
    axes: dict[str, Literal["left", "right"]] = Field(default_factory=dict, max_length=12)
    indexed: bool = False
    legend: bool = True
    hidden_series: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("hidden_series")
    @classmethod
    def safe_hidden(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 200 or any(ord(c) < 32 for c in item) for item in value):
            raise ValueError("hidden series names must be 1 to 200 characters with no control characters")
        return value


class TimelineOptions(StrictModel):
    pass


class KpiOptions(StrictModel):

    compare_prior: bool = True


class LeaderboardOptions(StrictModel):

    top_n: int = Field(8, ge=1, le=10)


class TreemapOptions(StrictModel):

    measure: Literal["tokens", "cost"] = "tokens"


class HeatOptions(StrictModel):
    pass


class LiveOpsOptions(StrictModel):
    pass


class FlowOptions(StrictModel):

    measure: Literal["tokens", "cost"] = "tokens"


class ScatterOptions(StrictModel):
    pass


ImpactMetric = Literal["total_tokens", "estimated_cost_nano_usd", "input_tokens", "output_tokens",
                       "cache_read_tokens", "usage_count"]


class ImpactOptions(StrictModel):

    annotation_id: str = Field("", max_length=64, pattern=r"^[0-9a-fA-F-]*$")
    metric: ImpactMetric = "estimated_cost_nano_usd"
    days: int = Field(7, ge=1, le=30)


VIZ_OPTIONS: dict[str, type[StrictModel]] = {
    "timeline": TimelineOptions, "kpi": KpiOptions, "leaderboard": LeaderboardOptions,
    "treemap": TreemapOptions, "heat": HeatOptions,
    "vitals": LiveOpsOptions, "hot": LiveOpsOptions, "events": LiveOpsOptions,
    "fleet": LiveOpsOptions, "runway": LiveOpsOptions, "swimlanes": LiveOpsOptions,
    "flow": FlowOptions, "scatter": ScatterOptions, "impact": ImpactOptions, "health": LiveOpsOptions,
    "pack": LiveOpsOptions, "agents": LiveOpsOptions,
}
Viz = Literal["timeline", "kpi", "leaderboard", "treemap", "heat", "vitals", "hot", "events", "fleet", "runway", "swimlanes",
           "flow", "scatter", "impact", "health", "pack", "agents"]


class ChartWrite(StrictModel):
    id: UUID | None = None
    viz: Viz = "timeline"
    options: dict = Field(default_factory=dict)
    title: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    series: list[ChartSeries] = Field(min_length=1, max_length=12)
    filters: StatsFilters = Field(default_factory=StatsFilters)
    range: ChartRange = Field(default_factory=ChartRange)
    resolution: Resolution = "auto"
    display: ChartDisplay = Field(default_factory=ChartDisplay)

    @field_validator("title")
    @classmethod
    def safe_title(cls, value: str) -> str:
        if any(ord(c) < 32 for c in value):
            raise ValueError("title contains a control character")
        return value.strip()

    @model_validator(mode="after")
    def valid_options(self):
        self.options = VIZ_OPTIONS[self.viz].model_validate(self.options).model_dump()
        return self

    @model_validator(mode="after")
    def bounded_series(self):
        if sum(2 if item.operation == "comparison" else 1 for item in self.series) > 12:
            raise ValueError("chart exceeds 12 expanded series")
        if any(key not in {series.metric for series in self.series} for key in self.display.axes):
            raise ValueError("axis keys must name a chart metric")
        return self


class ChartPatch(ChartWrite):
    revision: int = Field(ge=1)


class AnnotationWrite(StrictModel):
    occurred_at: datetime
    kind: Literal["manual", "rule"] = "manual"
    label: str = Field(min_length=1, max_length=240)
    scope: StatsFilters = Field(default_factory=StatsFilters)
    rule_hash: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    reference: str | None = Field(None, max_length=160)
    basis: Literal["manual", "observed", "git_commit"] = "manual"

    @model_validator(mode="after")
    def valid_fields(self):
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at needs timezone")
        if self.kind == "rule" and not self.rule_hash:
            raise ValueError("rule annotation needs hash")
        if any(ord(c) < 32 for c in self.label):
            raise ValueError("label contains a control character")
        if self.reference is not None:
            if (self.reference.startswith(("/", "\\")) or ".." in self.reference.split("/")
                    or any(ord(c) < 32 for c in self.reference)):
                raise ValueError("reference must be a safe relative label")
        return self


class AnnotationPatch(AnnotationWrite):
    revision: int = Field(ge=1)


class BackfillRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")


class QueryBatchRequest(BaseModel):
    """Up to 32 single-query bodies; each is validated per item so one bad item never fails the batch."""
    model_config = ConfigDict(extra="forbid")
    items: list[dict] = Field(min_length=1, max_length=32)


class TripwireWrite(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    chart_id: UUID | None = None
    query: dict
    window_minutes: int = Field(15, ge=1, le=1440)
    comparator: Literal[">", "<"]
    threshold: float = Field(allow_inf_nan=False)
    for_minutes: int = Field(0, ge=0, le=1440)
    cooldown_minutes: int = Field(0, ge=0, le=10080)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if any(ord(c) < 32 for c in value) or not value.strip():
            raise ValueError("name must be nonempty and contain no control characters")
        return value.strip()

    @model_validator(mode="after")
    def valid_query(self):
        body = {k: v for k, v in self.query.items() if k not in ("from", "to")}
        if body.get("operation", "summary") != "summary":
            raise ValueError("tripwire query must use the summary operation")
        body["operation"] = "summary"
        now = datetime.now(timezone.utc)
        QueryRequest.model_validate({**body, "from": now - timedelta(days=1), "to": now})
        self.query = body
        return self
