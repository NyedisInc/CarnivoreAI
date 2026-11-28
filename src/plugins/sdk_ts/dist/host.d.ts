import type { AiCallInput, AiCapability, FetchOptions, FetchResponse, FlowFeedOptions, FlowRunOptions, ProjectRow, RpcSender, SessionRow } from "./types.js";
export declare class SessionsNamespace {
    private readonly send;
    constructor(send: RpcSender);
    list(): Promise<{
        sessions: SessionRow[];
    }>;
    get(refOrParams: string | {
        ref: string;
    }): Promise<{
        session: SessionRow | null;
    }>;
    output(refOrParams: string | {
        ref: string;
        lines?: number;
    }, lines?: number): Promise<{
        lines: string[];
    }>;
    permissionMode(refOrParams: string | {
        ref: string;
    }): Promise<{
        mode: string | null;
    }>;
    permission_mode: (refOrParams: string | {
        ref: string;
    }) => Promise<{
        mode: string | null;
    }>;
    message(refOrParams: string | {
        ref: string;
        line: string;
        owner_token: string;
    }, line?: string, ownerToken?: string): Promise<{
        delivered: boolean;
    }>;
    create(params: {
        project: number;
        prompt?: string;
        family?: string;
    }): Promise<{
        ref: string;
    }>;
    control(refOrParams: string | {
        ref: string;
        action: "restart" | "stop" | "sleep" | "wake";
    }, action?: "restart" | "stop" | "sleep" | "wake"): Promise<{
        ok: boolean;
    }>;
}
export declare class StorageNamespace {
    private readonly send;
    constructor(send: RpcSender);
    get<T = unknown>(keyOrParams: string | {
        key: string;
    }): Promise<{
        value: T | null;
    }>;
    put(keyOrParams: string | {
        key: string;
        value: unknown;
    }, value?: unknown): Promise<Record<string, never>>;
    delete(keyOrParams: string | {
        key: string;
    }): Promise<Record<string, never>>;
    list(prefixOrParams?: string | {
        prefix?: string;
    }): Promise<{
        keys: string[];
    }>;
}
export declare class NotifyNamespace {
    private readonly send;
    constructor(send: RpcSender);
    toast(refOrParams: string | {
        ref: string;
        title: string;
    }, title?: string): Promise<Record<string, never>>;
    alert(keyOrParams: string | {
        key: string;
        severity: "info" | "warning" | "error";
        title: string;
        params?: Record<string, unknown>;
    }, severity?: "info" | "warning" | "error", title?: string, extraParams?: Record<string, unknown>): Promise<Record<string, never>>;
}
export declare class ProjectsNamespace {
    private readonly send;
    constructor(send: RpcSender);
    list(): Promise<{
        projects: ProjectRow[];
    }>;
    git(projectOrParams: number | {
        project: number;
        op: "status" | "branch" | "remote" | "diff_names";
    }, op?: "status" | "branch" | "remote" | "diff_names"): Promise<Record<string, unknown>>;
    snapshot(projectOrParams: number | {
        project: number;
        turn: string | number;
    }, turn?: string | number): Promise<{
        ref: string;
    }>;
}
export declare class Host {
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
        write: (folder: string, name: string, bytes: Uint8Array | Buffer | string) => Promise<{
            path: string;
        }>;
        writeText: (folder: string, name: string, text: string) => Promise<{
            path: string;
        }>;
    };
    readonly ledger: {
        read: () => Promise<Record<string, unknown>>;
    };
    constructor(send: RpcSender);
    httpFetch(url: string, opts?: FetchOptions): Promise<FetchResponse>;
    http_fetch: (url: string, method?: string, headers?: Record<string, string>, body?: string | null) => Promise<FetchResponse>;
    aiCall<T = unknown>(feature: string, capability: AiCapability, input: AiCallInput): Promise<T>;
    ai_call: <T = unknown>(feature: string, capability: AiCapability, input: AiCallInput) => Promise<T>;
    ledgerRead(): Promise<Record<string, unknown>>;
    ledger_read: () => Promise<Record<string, unknown>>;
    topicPublish(name: string, key?: string | null): Promise<Record<string, never>>;
    topic_publish: (name: string, key?: string | null) => Promise<Record<string, never>>;
    uiInvalidate(surface?: string | null): Promise<Record<string, never>>;
    ui_invalidate: (surface?: string | null) => Promise<Record<string, never>>;
    uiSlotPublish(slot: string, items: Record<string, unknown>[]): Promise<Record<string, unknown>>;
    ui_slot_publish: (slot: string, items: Record<string, unknown>[]) => Promise<Record<string, unknown>>;
    exportsWrite(folder: string, name: string, bytes: Uint8Array | Buffer | string): Promise<{
        path: string;
    }>;
    exports_write: (folder: string, name: string, bytes: Uint8Array | Buffer | string) => Promise<{
        path: string;
    }>;
    processSnapshot(): Promise<Record<string, unknown>>;
    process_snapshot: () => Promise<Record<string, unknown>>;
    mcpConfig(session?: string | null): Promise<Record<string, unknown>>;
    mcp_config: (session?: string | null) => Promise<Record<string, unknown>>;
    mcpLinks(session?: string | null): Promise<Record<string, unknown>>;
    mcp_links: (session?: string | null) => Promise<Record<string, unknown>>;
    flowRun(id: string, opts?: FlowRunOptions): Promise<Record<string, unknown>>;
    flow_run: (id: string, opts?: FlowRunOptions) => Promise<Record<string, unknown>>;
    flowRunPart(token: string, index: number): Promise<Record<string, unknown>>;
    flow_run_part: (token: string, index: number) => Promise<Record<string, unknown>>;
    flowFeed(id: string, topic: string, opts?: FlowFeedOptions): Promise<Record<string, unknown>>;
    flow_feed: (id: string, topic: string, opts?: FlowFeedOptions) => Promise<Record<string, unknown>>;
    flowTasks(query?: string, limit?: number): Promise<Record<string, unknown>>;
    flow_tasks: (query?: string, limit?: number) => Promise<Record<string, unknown>>;
    serviceCall(service: string, method: string, args?: Record<string, unknown>): Promise<Record<string, unknown>>;
    service_call: (service: string, method: string, args?: Record<string, unknown>) => Promise<Record<string, unknown>>;
    eventsEmit(event: string, payload?: Record<string, unknown>): Promise<Record<string, unknown>>;
    events_emit: (event: string, payload?: Record<string, unknown>) => Promise<Record<string, unknown>>;
    log(level: string, event: string, fields?: Record<string, unknown>): Promise<void>;
}
