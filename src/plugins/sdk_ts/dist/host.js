function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
}
export class SessionsNamespace {
    send;
    constructor(send) {
        this.send = send;
    }
    async list() {
        return (await this.send("sessions.list", {}));
    }
    async get(refOrParams) {
        const params = isRecord(refOrParams) ? refOrParams : { ref: refOrParams };
        return (await this.send("sessions.get", params));
    }
    async output(refOrParams, lines = 100) {
        const params = isRecord(refOrParams) ? refOrParams : { ref: refOrParams, lines };
        return (await this.send("sessions.output", params));
    }
    async permissionMode(refOrParams) {
        const params = isRecord(refOrParams) ? refOrParams : { ref: refOrParams };
        return (await this.send("sessions.permission_mode", params));
    }
    permission_mode = (refOrParams) => this.permissionMode(refOrParams);
    async message(refOrParams, line, ownerToken) {
        const params = isRecord(refOrParams)
            ? refOrParams
            : { ref: refOrParams, line: line ?? "", owner_token: ownerToken ?? "" };
        return (await this.send("sessions.message", params));
    }
    async create(params) {
        return (await this.send("sessions.create", params));
    }
    async control(refOrParams, action) {
        const params = isRecord(refOrParams) ? refOrParams : { ref: refOrParams, action: action ?? "restart" };
        return (await this.send("sessions.control", params));
    }
}
export class StorageNamespace {
    send;
    constructor(send) {
        this.send = send;
    }
    async get(keyOrParams) {
        const params = isRecord(keyOrParams) ? keyOrParams : { key: keyOrParams };
        return (await this.send("storage.get", params));
    }
    async put(keyOrParams, value) {
        const params = isRecord(keyOrParams) ? keyOrParams : { key: keyOrParams, value };
        return (await this.send("storage.put", params));
    }
    async delete(keyOrParams) {
        const params = isRecord(keyOrParams) ? keyOrParams : { key: keyOrParams };
        return (await this.send("storage.delete", params));
    }
    async list(prefixOrParams = "") {
        const params = isRecord(prefixOrParams) ? prefixOrParams : { prefix: prefixOrParams };
        return (await this.send("storage.list", params));
    }
}
export class NotifyNamespace {
    send;
    constructor(send) {
        this.send = send;
    }
    async toast(refOrParams, title) {
        const params = isRecord(refOrParams) ? refOrParams : { ref: refOrParams, title: title ?? "" };
        return (await this.send("notify.toast", params));
    }
    async alert(keyOrParams, severity, title, extraParams) {
        const params = isRecord(keyOrParams)
            ? keyOrParams
            : {
                key: keyOrParams,
                severity: severity ?? "info",
                title: title ?? "",
                params: extraParams ?? {},
            };
        return (await this.send("notify.alert", params));
    }
}
export class ProjectsNamespace {
    send;
    constructor(send) {
        this.send = send;
    }
    async list() {
        return (await this.send("projects.list", {}));
    }
    async git(projectOrParams, op) {
        const params = isRecord(projectOrParams)
            ? projectOrParams
            : { project: projectOrParams, op: op ?? "status" };
        return (await this.send("projects.git", params));
    }
    async snapshot(projectOrParams, turn) {
        const params = isRecord(projectOrParams)
            ? projectOrParams
            : { project: projectOrParams, turn: turn ?? 0 };
        return (await this.send("projects.snapshot", params));
    }
}
export class Host {
    call;
    sessions;
    storage;
    notify;
    projects;
    service;
    events;
    topic;
    ui;
    exports;
    ledger;
    constructor(send) {
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
    async httpFetch(url, opts = {}) {
        const headers = { ...(opts.headers ?? {}) };
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
        }));
    }
    http_fetch = (url, method = "GET", headers, body) => this.httpFetch(url, { method, headers, body });
    async aiCall(feature, capability, input) {
        const res = (await this.call("ai.call", { feature, capability, input }));
        return res.output;
    }
    ai_call = (feature, capability, input) => this.aiCall(feature, capability, input);
    async ledgerRead() {
        return (await this.call("ledger.read", {}));
    }
    ledger_read = () => this.ledgerRead();
    async topicPublish(name, key) {
        const params = { name };
        if (key !== undefined) {
            params.key = key;
        }
        return (await this.call("topic.publish", params));
    }
    topic_publish = (name, key) => this.topicPublish(name, key);
    async uiInvalidate(surface) {
        const params = {};
        if (surface !== undefined && surface !== null) {
            params.surface = surface;
        }
        return (await this.call("ui.invalidate", params));
    }
    ui_invalidate = (surface) => this.uiInvalidate(surface);
    async uiSlotPublish(slot, items) {
        return (await this.call("ui.slot.publish", { slot, items }));
    }
    ui_slot_publish = (slot, items) => this.uiSlotPublish(slot, items);
    async exportsWrite(folder, name, bytes) {
        const b64 = typeof bytes === "string" ? bytes : Buffer.from(bytes).toString("base64");
        return (await this.call("exports.write", { folder, name, bytes: b64 }));
    }
    exports_write = (folder, name, bytes) => this.exportsWrite(folder, name, bytes);
    async processSnapshot() {
        return (await this.call("process.snapshot", {}));
    }
    process_snapshot = () => this.processSnapshot();
    async mcpConfig(session) {
        return (await this.call("mcp.config", session ? { session } : {}));
    }
    mcp_config = (session) => this.mcpConfig(session);
    async mcpLinks(session) {
        return (await this.call("mcp.links", session ? { session } : {}));
    }
    mcp_links = (session) => this.mcpLinks(session);
    async flowRun(id, opts = {}) {
        const params = {
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
        return (await this.call("flow.run", params));
    }
    flow_run = (id, opts = {}) => this.flowRun(id, opts);
    async flowRunPart(token, index) {
        return (await this.call("flow.run_part", { token, index }));
    }
    flow_run_part = (token, index) => this.flowRunPart(token, index);
    async flowFeed(id, topic, opts = {}) {
        const params = {
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
        return (await this.call("flow.feed", params));
    }
    flow_feed = (id, topic, opts = {}) => this.flowFeed(id, topic, opts);
    async flowTasks(query = "", limit = 30) {
        return (await this.call("flow.tasks", { query, limit }));
    }
    flow_tasks = (query = "", limit = 30) => this.flowTasks(query, limit);
    async serviceCall(service, method, args = {}) {
        return (await this.call("service.call", { service, method, args }));
    }
    service_call = (service, method, args = {}) => this.serviceCall(service, method, args);
    async eventsEmit(event, payload = {}) {
        return (await this.call("events.emit", { event, payload }));
    }
    events_emit = (event, payload = {}) => this.eventsEmit(event, payload);
    async log(level, event, fields = {}) {
        await this.call("log", { level, event, fields });
    }
}
