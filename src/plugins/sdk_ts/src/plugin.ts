import { AsyncLocalStorage } from "node:async_hooks";
import type { Readable, Writable } from "node:stream";

import {
  API_VERSION,
  FrameLimitError,
  HostError,
  NdjsonSplitter,
  RPC_ERROR_CODES,
  RpcClientTransport,
  RpcMethodError,
  encodeFrame,
} from "./frames.js";
import { Host } from "./host.js";
import { connectSocket, type SocketHost } from "./socket.js";
import type {
  ChannelEvent,
  ChannelHandler,
  CommandHandler,
  EventHandler,
  InitializeParams,
  InitializeResult,
  JsonRpcRequest,
  JsonRpcResponse,
  RouteHandler,
  RouteRequest,
  ServiceHandler,
  TimerHandler,
  ToolCaller,
  ToolGate,
  ToolHandler,
  ToolSpec,
  UiDocument,
  UiHandler,
  WebhookHandler,
} from "./types.js";

export interface ServeOptions {
  mode?: "rpc" | "oneshot";
  input?: Readable;
  output?: Writable;
  sockPath?: string;
  redirectConsole?: boolean;
}

export interface ToolOptions {
  name: string;
  description: string;
  inputSchema?: Record<string, unknown>;
  gate?: ToolGate;
}

const busTokenStorage = new AsyncLocalStorage<string | undefined>();

function extractBusToken(params: Record<string, unknown>): string | undefined {
  const raw = params._bus_token;
  return typeof raw === "string" && raw.length > 0 ? raw : undefined;
}

function withBusToken(method: string, params: Record<string, unknown>): Record<string, unknown> {
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
  private readonly toolsMeta = new Map<string, ToolSpec>();
  private readonly toolHandlers = new Map<string, ToolHandler>();
  private readonly routeHandlers = new Map<string, RouteHandler>();
  private readonly eventHandlers = new Map<string, EventHandler>();
  private readonly timerHandlers = new Map<string, TimerHandler>();
  private readonly uiHandlers = new Map<string, UiHandler>();
  private readonly commandHandlers = new Map<string, CommandHandler>();
  private readonly serviceHandlers = new Map<string, Map<string, ServiceHandler>>();
  private readonly channelHandlers = new Map<string, ChannelHandler>();

  settings: Record<string, unknown> = {};
  granted: string[] = [];
  pluginId = "";
  dataDir = "";
  tier = "";
  locale = "en";
  host: Host;

  private transport: RpcClientTransport | null = null;

  constructor() {
    this.host = new Host((method, params) => {
      if (!this.transport) {
        return Promise.reject(new Error("the plugin is not connected to a host"));
      }
      return this.transport.request(method, withBusToken(method, params));
    });
  }

  tool(
    nameOrOpts: string | ToolOptions,
    descriptionOrHandler: string | ToolHandler,
    inputSchemaOrHandler?: Record<string, unknown> | ToolHandler,
    gateOrHandler?: ToolGate | ToolHandler,
    handlerArg?: ToolHandler,
  ): this {
    let spec: ToolSpec;
    let handler: ToolHandler;

    if (typeof nameOrOpts === "object") {
      spec = {
        name: nameOrOpts.name,
        description: nameOrOpts.description,
        inputSchema: nameOrOpts.inputSchema ?? { type: "object" },
        gate: nameOrOpts.gate ?? "read",
      };
      handler = descriptionOrHandler as ToolHandler;
    } else if (typeof inputSchemaOrHandler === "function") {
      spec = {
        name: nameOrOpts,
        description: descriptionOrHandler as string,
        inputSchema: { type: "object" },
        gate: "read",
      };
      handler = inputSchemaOrHandler;
    } else if (typeof gateOrHandler === "function") {
      spec = {
        name: nameOrOpts,
        description: descriptionOrHandler as string,
        inputSchema: inputSchemaOrHandler ?? { type: "object" },
        gate: "read",
      };
      handler = gateOrHandler;
    } else {
      spec = {
        name: nameOrOpts,
        description: descriptionOrHandler as string,
        inputSchema: inputSchemaOrHandler ?? { type: "object" },
        gate: gateOrHandler ?? "read",
      };
      handler = handlerArg as ToolHandler;
    }

    if (typeof handler !== "function") {
      throw new TypeError(`tool(${spec.name}) requires a handler function`);
    }
    this.toolsMeta.set(spec.name, spec);
    this.toolHandlers.set(spec.name, handler);
    return this;
  }

  route(name: string, handler: RouteHandler): this {
    this.routeHandlers.set(name, handler);
    return this;
  }

  on(family: string, handler: EventHandler): this {
    this.eventHandlers.set(family, handler);
    return this;
  }

  onEvent(family: string, handler: EventHandler): this {
    return this.on(family, handler);
  }

  on_event(family: string, handler: EventHandler): this {
    return this.on(family, handler);
  }

  timer(name: string, handler: TimerHandler): this {
    this.timerHandlers.set(name, handler);
    return this;
  }

  ui(surface: string, handler: UiHandler): this {
    this.uiHandlers.set(surface, handler);
    return this;
  }

  webhook(hookName: string, handler: WebhookHandler): this {
    const family = `webhook.${hookName}`;
    return this.on(family, async (seq, rawPayload) => {
      let inner: unknown = rawPayload;
      let hook = hookName;
      if (rawPayload !== null && typeof rawPayload === "object" && !Array.isArray(rawPayload)) {
        const rec = rawPayload as Record<string, unknown>;
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

  command(id: string, handler: CommandHandler): this {
    this.commandHandlers.set(id, handler);
    return this;
  }

  channel(name: string, handler: ChannelHandler): this {
    this.channelHandlers.set(name, handler);
    return this;
  }

  service(
    name: string,
    methodOrMap: string | Record<string, ServiceHandler>,
    handler?: ServiceHandler,
  ): this {
    let table = this.serviceHandlers.get(name);
    if (!table) {
      table = new Map<string, ServiceHandler>();
      this.serviceHandlers.set(name, table);
    }
    if (typeof methodOrMap === "string") {
      if (typeof handler !== "function") {
        throw new TypeError(`service(${name}, ${methodOrMap}) requires a handler`);
      }
      table.set(methodOrMap, handler);
    } else {
      for (const [m, fn] of Object.entries(methodOrMap)) {
        table.set(m, fn);
      }
    }
    return this;
  }

  async handle(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
    if (method === "initialize") {
      const init = params as InitializeParams;
      this.settings = init.settings && typeof init.settings === "object" ? { ...init.settings } : {};
      this.granted = Array.isArray(init.granted) ? [...init.granted] : [];
      this.pluginId = typeof init.plugin_id === "string" ? init.plugin_id : "";
      this.dataDir = typeof init.data_dir === "string" ? init.data_dir : "";
      this.tier = typeof init.tier === "string" ? init.tier : "";
      this.locale = typeof init.locale === "string" ? init.locale : "en";
      const result: InitializeResult = {
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
        : {}) as Record<string, unknown>;
      const caller = (params.caller && typeof params.caller === "object" ? params.caller : {}) as ToolCaller;
      const out = await fn(args, caller);
      if (out !== null && typeof out === "object" && Array.isArray((out as Record<string, unknown>).content)) {
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
      return await fn(params as RouteRequest);
    }
    if (method === "event.deliver") {
      const family = String(params.family ?? "");
      const fn = this.eventHandlers.get(family);
      if (!fn) {
        throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown event family: ${family}`);
      }
      await fn(params.seq as number | null | undefined, params.payload);
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
        : {}) as Record<string, unknown>;
      const doc: UiDocument = await fn(uiParams);
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
      const args = (params.args && typeof params.args === "object" ? params.args : {}) as Record<string, unknown>;
      return await fn(args, { service: svc, method: meth });
    }
    if (method === "channel.send") {
      const ch = String(params.channel ?? "");
      const fn = this.channelHandlers.get(ch);
      if (!fn) {
        throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown channel: ${ch}`);
      }
      const ev = (params.event && typeof params.event === "object" ? params.event : {}) as ChannelEvent;
      const cfg = (params.config && typeof params.config === "object" ? params.config : {}) as Record<string, unknown>;
      return await fn(ev, cfg);
    }
    throw new RpcMethodError(RPC_ERROR_CODES.METHOD_NOT_FOUND, `unknown method: ${method}`);
  }

  private _installConsoleRedirect(enabled: boolean): () => void {
    if (!enabled) {
      return () => {};
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
    ] as const;
    type ConsoleMethod = (typeof methods)[number];
    const consoleObj = console as unknown as Record<ConsoleMethod, (...args: unknown[]) => void>;
    const originals = new Map<ConsoleMethod, (...args: unknown[]) => void>();
    for (const name of methods) {
      const orig = consoleObj[name];
      if (typeof orig === "function") {
        originals.set(name, orig);
        consoleObj[name] = (...args: unknown[]) => {
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

  async serve(opts: ServeOptions = {}): Promise<void> {
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
    } finally {
      restoreConsole();
    }
  }

  private async _serveOneshot(input: Readable, output: Writable, explicitSockPath?: string): Promise<void> {
    const sockPath = (explicitSockPath ?? process.env.CARNIVORE_PLUGIN_SOCK ?? "").trim();
    if (sockPath) {
      const origHost = this.host;
      let socketPromise: Promise<SocketHost> | null = null;
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
      } finally {
        disposed = true;
        this.host = origHost;
        const pending = socketPromise as Promise<SocketHost> | null;
        if (pending) {
          const sh = await pending.catch(() => null);
          sh?.close();
        }
      }
      return;
    }
    await this._runSingleOneshotRequest(input, output);
  }

  private async _runSingleOneshotRequest(input: Readable, output: Writable): Promise<void> {
    const line = await readOneFrame(input);
    if (!line) {
      return;
    }
    let frame: JsonRpcRequest;
    try {
      frame = JSON.parse(line) as JsonRpcRequest;
    } catch {
      output.write(encodeFrame({ id: 1, error: { code: RPC_ERROR_CODES.INVALID_REQUEST, message: "bad_json" } }));
      return;
    }
    const rid = frame.id ?? 1;
    try {
      const params = frame.params ?? {};
      const result = await busTokenStorage.run(extractBusToken(params), () => this.handle(frame.method, params));
      output.write(encodeFrame({ id: rid, result: result ?? {} }));
    } catch (err) {
      output.write(encodeFrame({ id: rid, error: formatError(err) }));
    }
  }

  private async _serveRpc(input: Readable, output: Writable): Promise<void> {
    const splitter = new NdjsonSplitter();
    const transport = new RpcClientTransport((line) => {
      output.write(line);
    });
    this.transport = transport;
    const inflight = new Set<Promise<void>>();

    const dispatchLine = (line: string) => {
      let frame: Record<string, unknown>;
      try {
        frame = JSON.parse(line) as Record<string, unknown>;
      } catch {
        return;
      }
      if (!frame || typeof frame !== "object") {
        return;
      }
      if (typeof frame.method !== "string") {
        if (typeof frame.id === "number") {
          transport.handleResponse(frame as unknown as JsonRpcResponse);
        }
        return;
      }
      const req = frame as unknown as JsonRpcRequest;
      const task = (async () => {
        const rid = req.id;
        try {
          const params = req.params ?? {};
          const result = await busTokenStorage.run(extractBusToken(params), () => this.handle(req.method, params));
          if (rid !== undefined && rid !== null) {
            output.write(encodeFrame({ id: rid, result: result ?? {} }));
          }
        } catch (err) {
          if (rid !== undefined && rid !== null) {
            output.write(encodeFrame({ id: rid, error: formatError(err) }));
          }
        }
      })();
      inflight.add(task);
      void task.finally(() => inflight.delete(task));
    };

    try {
      await new Promise<void>((resolve, reject) => {
        const onData = (chunk: Buffer | string) => {
          try {
            for (const line of splitter.feed(chunk)) {
              dispatchLine(line);
            }
          } catch (err) {
            cleanup();
            reject(err);
          }
        };
        const onEnd = () => {
          cleanup();
          resolve();
        };
        const onError = (err: Error) => {
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
        if (typeof (input as unknown as { resume?: () => void }).resume === "function") {
          (input as unknown as { resume: () => void }).resume();
        }
      });
      if (inflight.size > 0) {
        await Promise.allSettled([...inflight]);
      }
    } finally {
      transport.rejectAll(new Error("stdio stream closed"));
      this.transport = null;
    }
  }
}

function formatError(err: unknown): { code: number; message: string; data?: Record<string, unknown> } {
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

function readOneFrame(input: Readable): Promise<string> {
  const splitter = new NdjsonSplitter();
  return new Promise((resolve, reject) => {
    let settled = false;
    const chunks: Buffer[] = [];
    const finish = (line: string) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolve(line);
    };
    const fail = (err: Error) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      reject(err);
    };
    const onData = (chunk: Buffer | string) => {
      const buf = typeof chunk === "string" ? Buffer.from(chunk, "utf8") : Buffer.from(chunk);
      chunks.push(buf);
      try {
        const lines = splitter.feed(buf);
        if (lines.length > 0) {
          finish(lines[0]);
        }
      } catch (err) {
        fail(err instanceof Error ? err : new Error(String(err)));
      }
    };
    const onEnd = () => {
      const rest = Buffer.concat(chunks).toString("utf8").trim();
      finish(rest);
    };
    const onError = (err: Error) => fail(err);
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
    if (typeof (input as unknown as { resume?: () => void }).resume === "function") {
      (input as unknown as { resume: () => void }).resume();
    }
  });
}
