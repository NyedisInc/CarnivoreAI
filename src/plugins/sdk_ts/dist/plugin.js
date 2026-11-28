import { AsyncLocalStorage } from "node:async_hooks";
import { API_VERSION, FrameLimitError, HostError, NdjsonSplitter, RPC_ERROR_CODES, RpcClientTransport, RpcMethodError, encodeFrame, } from "./frames.js";
import { Host } from "./host.js";
import { connectSocket } from "./socket.js";
const busTokenStorage = new AsyncLocalStorage();
function extractBusToken(params) {
    const raw = params._bus_token;
    return typeof raw === "string" && raw.length > 0 ? raw : undefined;
}
function withBusToken(method, params) {
    if (method === "service.call" && !("_bus_token" in params)) {
        const envTok = process.env.CARNIVORE_BUS_TOKEN?.trim();
        const tok = busTokenStorage.getStore() ?? (envTok || undefined);
        if (tok) {
            return { ...params, _bus_token: tok };
        }
    }
    return params;
}
export class Plugin {
    toolsMeta = new Map();
    toolHandlers = new Map();
    routeHandlers = new Map();
    eventHandlers = new Map();
    timerHandlers = new Map();
    uiHandlers = new Map();
    commandHandlers = new Map();
    serviceHandlers = new Map();
    channelHandlers = new Map();
    settings = {};
    granted = [];
    pluginId = "";
    dataDir = "";
    tier = "";
    locale = "en";
    host;
    transport = null;
    constructor() {
        this.host = new Host((method, params) => {
            if (!this.transport) {
                return Promise.reject(new Error("the plugin is not connected to a host"));
            }
            return this.transport.request(method, withBusToken(method, params));
        });
    }
    tool(nameOrOpts, descriptionOrHandler, inputSchemaOrHandler, gateOrHandler, handlerArg) {
        let spec;
        let handler;
        if (typeof nameOrOpts === "object") {
            spec = {
                name: nameOrOpts.name,
                description: nameOrOpts.description,
                inputSchema: nameOrOpts.inputSchema ?? { type: "object" },
                gate: nameOrOpts.gate ?? "read",
            };
            handler = descriptionOrHandler;
        }
        else if (typeof inputSchemaOrHandler === "function") {
            spec = {
                name: nameOrOpts,
                description: descriptionOrHandler,
                inputSchema: { type: "object" },
                gate: "read",
            };
            handler = inputSchemaOrHandler;
        }
        else if (typeof gateOrHandler === "function") {
            spec = {
                name: nameOrOpts,
                description: descriptionOrHandler,
                inputSchema: inputSchemaOrHandler ?? { type: "object" },
                gate: "read",
            };
            handler = gateOrHandler;
        }
        else {
            spec = {
                name: nameOrOpts,
                description: descriptionOrHandler,
                inputSchema: inputSchemaOrHandler ?? { type: "object" },
                gate: gateOrHandler ?? "read",
            };
            handler = handlerArg;
        }
        if (typeof handler !== "function") {
            throw new TypeError(`tool(${spec.name}) requires a handler function`);
        }
        this.toolsMeta.set(spec.name, spec);
        this.toolHandlers.set(spec.name, handler);
        return this;
    }
    route(name, handler) {
        this.routeHandlers.set(name, handler);
        return this;
    }
    on(family, handler) {
        this.eventHandlers.set(family, handler);
        return this;
    }
    onEvent(family, handler) {
        return this.on(family, handler);
    }
    on_event(family, handler) {
        return this.on(family, handler);
    }
    timer(name, handler) {
        this.timerHandlers.set(name, handler);
        return this;
    }
    ui(surface, handler) {
        this.uiHandlers.set(surface, handler);
        return this;
    }
    webhook(hookName, handler) {
        const family = `webhook.${hookName}`;
        return this.on(family, async (seq, rawPayload) => {
            let inner = rawPayload;
            let hook = hookName;
            if (rawPayload !== null && typeof rawPayload === "object" && !Array.isArray(rawPayload)) {
                const rec = rawPayload;
                if (typeof rec.hook === "string") {
                    hook = rec.hook;
                }
                if ("payload" in rec) {
                    inner = rec.payload;
                }
            }
            await handler(inner, seq, { hook, family });
        });
    }
    command(id, handler) {
        this.commandHandlers.set(id, handler);
        return this;
    }
    channel(name, handler) {
        this.channelHandlers.set(name, handler);
        return this;
    }
    service(name, methodOrMap, handler) {
        let table = this.serviceHandlers.get(name);
        if (!table) {
            table = new Map();
            this.serviceHandlers.set(name, table);
        }
        if (typeof methodOrMap === "string") {
            if (typeof handler !== "function") {
                throw new TypeError(`service(${name}, ${methodOrMap}) requires a handler`);
            }
            table.set(methodOrMap, handler);
        }
        else {
            for (const [m, fn] of Object.entries(methodOrMap)) {
                table.set(m, fn);
            }
        }
        return this;
    }
    async handle(method, params = {}) {
        if (method === "initialize") {
            const init = params;
            this.settings = init.settings && typeof init.settings === "object" ? { ...init.settings } : {};
            this.granted = Array.isArray(init.granted) ? [...init.granted] : [];
            this.pluginId = typeof init.plugin_id === "string" ? init.plugin_id : "";
            this.dataDir = typeof init.data_dir === "string" ? init.data_dir : "";
            this.tier = typeof init.tier === "string" ? init.tier : "";
            this.locale = typeof init.locale === "string" ? init.locale : "en";
            const result = {
                api_version: API_VERSION,
                capabilities: {
                    tools: this.toolsMeta.size > 0,
                    routes: this.routeHandlers.size > 0,
                    events: this.eventHandlers.size > 0,
                    timers: this.timerHandlers.size > 0,
                    services: this.serviceHandlers.size > 0,
                },
                subscriptions: [...this.eventHandlers.keys()].sort(),
            };
            return result;
        }
        if (method === "ping") {
            return { ts: 0 };
        }
        if (method === "shutdown") {
            return {};
        }
        if (method === "tools/list") {
            return { tools: [...this.toolsMeta.values()] };
        }
        if (method === "tools/call") {
            const name = String(params.name ?? "");
            const fn = this.toolHandlers.get(name);
            if (!fn) {
                throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown tool: ${name}`);
            }
            const args = (params.arguments && typeof params.arguments === "object"
                ? params.arguments
                : {});
            const caller = (params.caller && typeof params.caller === "object" ? params.caller : {});
            const out = await fn(args, caller);
            if (out !== null && typeof out === "object" && Array.isArray(out.content)) {
                return out;
            }
            return {
                content: [{ type: "text", text: typeof out === "string" ? out : JSON.stringify(out ?? "") }],
            };
        }
        if (method === "route.handle") {
            const routeName = String(params.route ?? "");
            const fn = this.routeHandlers.get(routeName);
            if (!fn) {
                throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown route: ${routeName}`);
            }
            return await fn(params);
        }
        if (method === "event.deliver") {
            const family = String(params.family ?? "");
            const fn = this.eventHandlers.get(family);
            if (!fn) {
                throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown event family: ${family}`);
            }
            await fn(params.seq, params.payload);
            return {};
        }
        if (method === "timer.tick") {
            const name = String(params.name ?? "");
            const fn = this.timerHandlers.get(name);
            if (!fn) {
                throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown timer: ${name}`);
            }
            await fn(Number(params.scheduled_for ?? 0));
            return {};
        }
        if (method === "ui.render") {
            const surface = String(params.surface ?? "");
            const fn = this.uiHandlers.get(surface);
            if (!fn) {
                throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, "unavailable");
            }
            const uiParams = (params.params && typeof params.params === "object"
                ? params.params
                : {});
            const doc = await fn(uiParams);
            return { document: doc };
        }
        if (method === "command.run") {
            const id = String(params.command ?? params.id ?? "");
            const fn = this.commandHandlers.get(id);
            if (!fn) {
                throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown command: ${id}`);
            }
            return await fn(params);
        }
        if (method === "service.call") {
            const svc = String(params.service ?? "");
            const meth = String(params.method ?? "");
            const fn = this.serviceHandlers.get(svc)?.get(meth);
            if (!fn) {
                throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown service method: ${svc}.${meth}`);
            }
            const args = (params.args && typeof params.args === "object" ? params.args : {});
            return await fn(args, { service: svc, method: meth });
        }
        if (method === "channel.send") {
            const ch = String(params.channel ?? "");
            const fn = this.channelHandlers.get(ch);
            if (!fn) {
                throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown channel: ${ch}`);
            }
            const ev = (params.event && typeof params.event === "object" ? params.event : {});
            const cfg = (params.config && typeof params.config === "object" ? params.config : {});
            return await fn(ev, cfg);
        }
        throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown method: ${method}`);
    }
    _installConsoleRedirect(enabled) {
        if (!enabled) {
            return () => { };
        }
        const methods = [
            "log",
            "info",
            "debug",
            "dir",
            "dirxml",
            "table",
            "count",
            "countReset",
            "timeLog",
            "timeEnd",
            "group",
            "groupCollapsed",
        ];
        const consoleObj = console;
        const originals = new Map();
        for (const name of methods) {
            const orig = consoleObj[name];
            if (typeof orig === "function") {
                originals.set(name, orig);
                consoleObj[name] = (...args) => {
                    console.error(...args);
                };
            }
        }
        return () => {
            for (const [name, orig] of originals.entries()) {
                consoleObj[name] = orig;
            }
        };
    }
    async serve(opts = {}) {
        const input = opts.input ?? process.stdin;
        const output = opts.output ?? process.stdout;
        const mode = opts.mode ?? (process.env.CARNIVORE_PLUGIN_MODE === "oneshot" ? "oneshot" : "rpc");
        const restoreConsole = this._installConsoleRedirect(opts.redirectConsole !== false);
        try {
            if (mode === "oneshot") {
                await this._serveOneshot(input, output, opts.sockPath);
                return;
            }
            await this._serveRpc(input, output);
        }
        finally {
            restoreConsole();
        }
    }
    async _serveOneshot(input, output, explicitSockPath) {
        const sockPath = (explicitSockPath ?? process.env.CARNIVORE_PLUGIN_SOCK ?? "").trim();
        if (sockPath) {
            const origHost = this.host;
            let socketPromise = null;
            let disposed = false;
            this.host = new Host(async (method, params) => {
                if (disposed) {
                    throw new Error("oneshot host disposed");
                }
                if (!socketPromise) {
                    socketPromise = connectSocket(sockPath).catch((err) => {
                        socketPromise = null;
                        throw err;
                    });
                }
                const socketHost = await socketPromise;
                return await socketHost.call(method, withBusToken(method, params));
            });
            try {
                await this._runSingleOneshotRequest(input, output);
            }
            finally {
                disposed = true;
                this.host = origHost;
                const pending = socketPromise;
                if (pending) {
                    const sh = await pending.catch(() => null);
                    sh?.close();
                }
            }
            return;
        }
        await this._runSingleOneshotRequest(input, output);
    }
    async _runSingleOneshotRequest(input, output) {
        const line = await readOneFrame(input);
        if (!line) {
            return;
        }
        let frame;
        try {
            frame = JSON.parse(line);
        }
        catch {
            output.write(encodeFrame({ id: 1, error: { code: RPC_ERROR_CODES.INVALID_REQUEST, message: "bad_json" } }));
            return;
        }
        const rid = frame.id ?? 1;
        try {
            const params = frame.params ?? {};
            const result = await busTokenStorage.run(extractBusToken(params), () => this.handle(frame.method, params));
            output.write(encodeFrame({ id: rid, result: result ?? {} }));
        }
        catch (err) {
            output.write(encodeFrame({ id: rid, error: formatError(err) }));
        }
    }
    async _serveRpc(input, output) {
        const splitter = new NdjsonSplitter();
        const transport = new RpcClientTransport((line) => {
            output.write(line);
        });
        this.transport = transport;
        const inflight = new Set();
        const dispatchLine = (line) => {
            let frame;
            try {
                frame = JSON.parse(line);
            }
            catch {
                return;
            }
            if (!frame || typeof frame !== "object") {
                return;
            }
            if (typeof frame.method !== "string") {
                if (typeof frame.id === "number") {
                    transport.handleResponse(frame);
                }
                return;
            }
            const req = frame;
            const task = (async () => {
                const rid = req.id;
                try {
                    const params = req.params ?? {};
                    const result = await busTokenStorage.run(extractBusToken(params), () => this.handle(req.method, params));
                    if (rid !== undefined && rid !== null) {
                        output.write(encodeFrame({ id: rid, result: result ?? {} }));
                    }
                }
                catch (err) {
                    if (rid !== undefined && rid !== null) {
                        output.write(encodeFrame({ id: rid, error: formatError(err) }));
                    }
                }
            })();
            inflight.add(task);
            void task.finally(() => inflight.delete(task));
        };
        try {
            await new Promise((resolve, reject) => {
                const onData = (chunk) => {
                    try {
                        for (const line of splitter.feed(chunk)) {
                            dispatchLine(line);
                        }
                    }
                    catch (err) {
                        cleanup();
                        reject(err);
                    }
                };
                const onEnd = () => {
                    cleanup();
                    resolve();
                };
                const onError = (err) => {
                    cleanup();
                    reject(err);
                };
                const cleanup = () => {
                    input.off("data", onData);
                    input.off("end", onEnd);
                    input.off("close", onEnd);
                    input.off("error", onError);
                };
                input.on("data", onData);
                input.on("end", onEnd);
                input.on("close", onEnd);
                input.on("error", onError);
                if (typeof input.resume === "function") {
                    input.resume();
                }
            });
            if (inflight.size > 0) {
                await Promise.allSettled([...inflight]);
            }
        }
        finally {
            transport.rejectAll(new Error("stdio stream closed"));
            this.transport = null;
        }
    }
}
function formatError(err) {
    if (err instanceof RpcMethodError) {
        return { code: err.code, message: err.message };
    }
    if (err instanceof HostError) {
        return { code: RPC_ERROR_CODES.INTERNAL_ERROR, message: "HostError" };
    }
    if (err instanceof FrameLimitError) {
        return { code: RPC_ERROR_CODES.TOO_LARGE, message: err.code };
    }
    const msg = err instanceof Error ? err.name || "Error" : "Error";
    return { code: RPC_ERROR_CODES.INTERNAL_ERROR, message: msg };
}
function readOneFrame(input) {
    const splitter = new NdjsonSplitter();
    return new Promise((resolve, reject) => {
        let settled = false;
        const chunks = [];
        const finish = (line) => {
            if (settled) {
                return;
            }
            settled = true;
            cleanup();
            resolve(line);
        };
        const fail = (err) => {
            if (settled) {
                return;
            }
            settled = true;
            cleanup();
            reject(err);
        };
        const onData = (chunk) => {
            const buf = typeof chunk === "string" ? Buffer.from(chunk, "utf8") : Buffer.from(chunk);
            chunks.push(buf);
            try {
                const lines = splitter.feed(buf);
                if (lines.length > 0) {
                    finish(lines[0]);
                }
            }
            catch (err) {
                fail(err instanceof Error ? err : new Error(String(err)));
            }
        };
        const onEnd = () => {
            const rest = Buffer.concat(chunks).toString("utf8").trim();
            finish(rest);
        };
        const onError = (err) => fail(err);
        const cleanup = () => {
            input.off("data", onData);
            input.off("end", onEnd);
            input.off("close", onEnd);
            input.off("error", onError);
        };
        input.on("data", onData);
        input.on("end", onEnd);
        input.on("close", onEnd);
        input.on("error", onError);
        if (typeof input.resume === "function") {
            input.resume();
        }
    });
}
