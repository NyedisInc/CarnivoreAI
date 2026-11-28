import type {
  AiCallInput,
  AiCapability,
  FetchOptions,
  FetchResponse,
  FlowFeedOptions,
  FlowRunOptions,
  ProjectRow,
  RpcSender,
  SessionRow,
} from "./types.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export class SessionsNamespace {
  constructor(private readonly send: RpcSender) {}

  async list(): Promise<{ sessions: SessionRow[] }> {
    return (await this.send("sessions.list", {})) as { sessions: SessionRow[] };
  }

  async get(refOrParams: string | { ref: string }): Promise<{ session: SessionRow | null }> {
    const params = isRecord(refOrParams) ? refOrParams : { ref: refOrParams };
    return (await this.send("sessions.get", params)) as { session: SessionRow | null };
  }

  async output(refOrParams: string | { ref: string; lines?: number }, lines = 100): Promise<{ lines: string[] }> {
    const params = isRecord(refOrParams) ? refOrParams : { ref: refOrParams, lines };
    return (await this.send("sessions.output", params)) as { lines: string[] };
  }

  async permissionMode(refOrParams: string | { ref: string }): Promise<{ mode: string | null }> {
    const params = isRecord(refOrParams) ? refOrParams : { ref: refOrParams };
    return (await this.send("sessions.permission_mode", params)) as { mode: string | null };
  }

  permission_mode = (refOrParams: string | { ref: string }): Promise<{ mode: string | null }> =>
    this.permissionMode(refOrParams);

  async message(
    refOrParams: string | { ref: string; line: string; owner_token: string },
    line?: string,
    ownerToken?: string,
  ): Promise<{ delivered: boolean }> {
    const params = isRecord(refOrParams)
      ? refOrParams
      : { ref: refOrParams, line: line ?? "", owner_token: ownerToken ?? "" };
    return (await this.send("sessions.message", params)) as { delivered: boolean };
  }

  async create(params: { project: number; prompt?: string; family?: string }): Promise<{ ref: string }> {
    return (await this.send("sessions.create", params)) as { ref: string };
  }

  async control(
    refOrParams: string | { ref: string; action: "restart" | "stop" | "sleep" | "wake" },
    action?: "restart" | "stop" | "sleep" | "wake",
  ): Promise<{ ok: boolean }> {
    const params = isRecord(refOrParams) ? refOrParams : { ref: refOrParams, action: action ?? "restart" };
    return (await this.send("sessions.control", params)) as { ok: boolean };
  }
}

export class StorageNamespace {
  constructor(private readonly send: RpcSender) {}

  async get<T = unknown>(keyOrParams: string | { key: string }): Promise<{ value: T | null }> {
    const params = isRecord(keyOrParams) ? keyOrParams : { key: keyOrParams };
    return (await this.send("storage.get", params)) as { value: T | null };
  }

  async put(keyOrParams: string | { key: string; value: unknown }, value?: unknown): Promise<Record<string, never>> {
    const params = isRecord(keyOrParams) ? keyOrParams : { key: keyOrParams, value };
    return (await this.send("storage.put", params)) as Record<string, never>;
  }

  async delete(keyOrParams: string | { key: string }): Promise<Record<string, never>> {
    const params = isRecord(keyOrParams) ? keyOrParams : { key: keyOrParams };
    return (await this.send("storage.delete", params)) as Record<string, never>;
  }

  async list(prefixOrParams: string | { prefix?: string } = ""): Promise<{ keys: string[] }> {
    const params = isRecord(prefixOrParams) ? prefixOrParams : { prefix: prefixOrParams };
    return (await this.send("storage.list", params)) as { keys: string[] };
  }
}

export class NotifyNamespace {
  constructor(private readonly send: RpcSender) {}

  async toast(refOrParams: string | { ref: string; title: string }, title?: string): Promise<Record<string, never>> {
    const params = isRecord(refOrParams) ? refOrParams : { ref: refOrParams, title: title ?? "" };
    return (await this.send("notify.toast", params)) as Record<string, never>;
  }

  async alert(
    keyOrParams: string | { key: string; severity: "info" | "warning" | "error"; title: string; params?: Record<string, unknown> },
    severity?: "info" | "warning" | "error",
    title?: string,
    extraParams?: Record<string, unknown>,
  ): Promise<Record<string, never>> {
    const params = isRecord(keyOrParams)
      ? keyOrParams
      : {
          key: keyOrParams,
          severity: severity ?? "info",
          title: title ?? "",
          params: extraParams ?? {},
        };
    return (await this.send("notify.alert", params)) as Record<string, never>;
  }
}

export class ProjectsNamespace {
  constructor(private readonly send: RpcSender) {}

  async list(): Promise<{ projects: ProjectRow[] }> {
    return (await this.send("projects.list", {})) as { projects: ProjectRow[] };
  }

  async git(
    projectOrParams: number | { project: number; op: "status" | "branch" | "remote" | "diff_names" },
    op?: "status" | "branch" | "remote" | "diff_names",
  ): Promise<Record<string, unknown>> {
    const params = isRecord(projectOrParams)
      ? projectOrParams
      : { project: projectOrParams, op: op ?? "status" };
    return (await this.send("projects.git", params)) as Record<string, unknown>;
  }

  async snapshot(
    projectOrParams: number | { project: number; turn: string | number },
    turn?: string | number,
  ): Promise<{ ref: string }> {
    const params = isRecord(projectOrParams)
      ? projectOrParams
      : { project: projectOrParams, turn: turn ?? 0 };
    return (await this.send("projects.snapshot", params)) as { ref: string };
  }
}

export class Host {
  readonly call: RpcSender;
  readonly sessions: SessionsNamespace;
  readonly storage: StorageNamespace;
  readonly notify: NotifyNamespace;
  readonly projects: ProjectsNamespace;
  readonly service: {
    call: (service: string, method: string, args?: Record<string, unknown>) => Promise<Record<string, unknown>>;
  };
  readonly events: {
    emit: (event: string, payload?: Record<string, unknown>) => Promise<Record<string, unknown>>;
  };
  readonly topic: {
    publish: (name: string, key?: string | null) => Promise<Record<string, never>>;
  };
  readonly ui: {
    invalidate: (surface?: string | null) => Promise<Record<string, never>>;
    slotPublish: (slot: string, items: Record<string, unknown>[]) => Promise<Record<string, unknown>>;
  };
  readonly exports: {
    write: (folder: string, name: string, bytes: Uint8Array | Buffer | string) => Promise<{ path: string }>;
    writeText: (folder: string, name: string, text: string) => Promise<{ path: string }>;
  };
  readonly ledger: {
    read: () => Promise<Record<string, unknown>>;
  };

  constructor(send: RpcSender) {
    this.call = send;
    this.sessions = new SessionsNamespace(send);
    this.storage = new StorageNamespace(send);
    this.notify = new NotifyNamespace(send);
    this.projects = new ProjectsNamespace(send);
    this.service = {
      call: (service, method, args = {}) => this.serviceCall(service, method, args),
    };
    this.events = {
      emit: (event, payload = {}) => this.eventsEmit(event, payload),
    };
    this.topic = {
      publish: (name, key) => this.topicPublish(name, key),
    };
    this.ui = {
      invalidate: (surface) => this.uiInvalidate(surface),
      slotPublish: (slot, items) => this.uiSlotPublish(slot, items),
    };
    this.exports = {
      write: (folder, name, bytes) => this.exportsWrite(folder, name, bytes),
      writeText: (folder, name, text) => this.exportsWrite(folder, name, Buffer.from(text, "utf8")),
    };
    this.ledger = {
      read: () => this.ledgerRead(),
    };
  }

  async httpFetch(url: string, opts: FetchOptions = {}): Promise<FetchResponse> {
    const headers: Record<string, string> = { ...(opts.headers ?? {}) };
    let body = opts.body ?? null;
    if (opts.json !== undefined && body === null) {
      body = JSON.stringify(opts.json);
      if (!Object.keys(headers).some((k) => k.toLowerCase() === "content-type")) {
        headers["Content-Type"] = "application/json";
      }
    }
    return (await this.call("http.fetch", {
      url,
      method: (opts.method ?? "GET").toUpperCase(),
      headers,
      body,
    })) as FetchResponse;
  }

  http_fetch = (
    url: string,
    method = "GET",
    headers?: Record<string, string>,
    body?: string | null,
  ): Promise<FetchResponse> => this.httpFetch(url, { method, headers, body });

  async aiCall<T = unknown>(feature: string, capability: AiCapability, input: AiCallInput): Promise<T> {
    const res = (await this.call("ai.call", { feature, capability, input })) as { output: T };
    return res.output;
  }

  ai_call = <T = unknown>(feature: string, capability: AiCapability, input: AiCallInput): Promise<T> =>
    this.aiCall<T>(feature, capability, input);

  async ledgerRead(): Promise<Record<string, unknown>> {
    return (await this.call("ledger.read", {})) as Record<string, unknown>;
  }

  ledger_read = (): Promise<Record<string, unknown>> => this.ledgerRead();

  async topicPublish(name: string, key?: string | null): Promise<Record<string, never>> {
    const params: Record<string, unknown> = { name };
    if (key !== undefined) {
      params.key = key;
    }
    return (await this.call("topic.publish", params)) as Record<string, never>;
  }

  topic_publish = (name: string, key?: string | null): Promise<Record<string, never>> =>
    this.topicPublish(name, key);

  async uiInvalidate(surface?: string | null): Promise<Record<string, never>> {
    const params: Record<string, unknown> = {};
    if (surface !== undefined && surface !== null) {
      params.surface = surface;
    }
    return (await this.call("ui.invalidate", params)) as Record<string, never>;
  }

  ui_invalidate = (surface?: string | null): Promise<Record<string, never>> => this.uiInvalidate(surface);

  async uiSlotPublish(slot: string, items: Record<string, unknown>[]): Promise<Record<string, unknown>> {
    return (await this.call("ui.slot.publish", { slot, items })) as Record<string, unknown>;
  }

  ui_slot_publish = (slot: string, items: Record<string, unknown>[]): Promise<Record<string, unknown>> =>
    this.uiSlotPublish(slot, items);

  async exportsWrite(folder: string, name: string, bytes: Uint8Array | Buffer | string): Promise<{ path: string }> {
    const b64 = typeof bytes === "string" ? bytes : Buffer.from(bytes).toString("base64");
    return (await this.call("exports.write", { folder, name, bytes: b64 })) as { path: string };
  }

  exports_write = (folder: string, name: string, bytes: Uint8Array | Buffer | string): Promise<{ path: string }> =>
    this.exportsWrite(folder, name, bytes);

  async processSnapshot(): Promise<Record<string, unknown>> {
    return (await this.call("process.snapshot", {})) as Record<string, unknown>;
  }

  process_snapshot = (): Promise<Record<string, unknown>> => this.processSnapshot();

  async mcpConfig(session?: string | null): Promise<Record<string, unknown>> {
    return (await this.call("mcp.config", session ? { session } : {})) as Record<string, unknown>;
  }

  mcp_config = (session?: string | null): Promise<Record<string, unknown>> => this.mcpConfig(session);

  async mcpLinks(session?: string | null): Promise<Record<string, unknown>> {
    return (await this.call("mcp.links", session ? { session } : {})) as Record<string, unknown>;
  }

  mcp_links = (session?: string | null): Promise<Record<string, unknown>> => this.mcpLinks(session);

  async flowRun(id: string, opts: FlowRunOptions = {}): Promise<Record<string, unknown>> {
    const params: Record<string, unknown> = {
      id,
      seed: opts.seed ?? "huddle_item",
      refresh: opts.refresh ?? false,
    };
    if (opts.start !== undefined) {
      params.start = opts.start;
    }
    if (opts.end !== undefined) {
      params.end = opts.end;
    }
    return (await this.call("flow.run", params)) as Record<string, unknown>;
  }

  flow_run = (id: string, opts: FlowRunOptions = {}): Promise<Record<string, unknown>> => this.flowRun(id, opts);

  async flowRunPart(token: string, index: number): Promise<Record<string, unknown>> {
    return (await this.call("flow.run_part", { token, index })) as Record<string, unknown>;
  }

  flow_run_part = (token: string, index: number): Promise<Record<string, unknown>> => this.flowRunPart(token, index);

  async flowFeed(id: string, topic: string, opts: FlowFeedOptions = {}): Promise<Record<string, unknown>> {
    const params: Record<string, unknown> = {
      id,
      topic,
      seed: opts.seed ?? "huddle_item",
    };
    if (opts.start !== undefined) {
      params.start = opts.start;
    }
    if (opts.cursor !== undefined) {
      params.cursor = opts.cursor;
    }
    return (await this.call("flow.feed", params)) as Record<string, unknown>;
  }

  flow_feed = (id: string, topic: string, opts: FlowFeedOptions = {}): Promise<Record<string, unknown>> =>
    this.flowFeed(id, topic, opts);

  async flowTasks(query = "", limit = 30): Promise<Record<string, unknown>> {
    return (await this.call("flow.tasks", { query, limit })) as Record<string, unknown>;
  }

  flow_tasks = (query = "", limit = 30): Promise<Record<string, unknown>> => this.flowTasks(query, limit);

  async serviceCall(service: string, method: string, args: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return (await this.call("service.call", { service, method, args })) as Record<string, unknown>;
  }

  service_call = (
    service: string,
    method: string,
    args: Record<string, unknown> = {},
  ): Promise<Record<string, unknown>> => this.serviceCall(service, method, args);

  async eventsEmit(event: string, payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return (await this.call("events.emit", { event, payload })) as Record<string, unknown>;
  }

  events_emit = (event: string, payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> =>
    this.eventsEmit(event, payload);

  async log(level: string, event: string, fields: Record<string, unknown> = {}): Promise<void> {
    await this.call("log", { level, event, fields });
  }
}
