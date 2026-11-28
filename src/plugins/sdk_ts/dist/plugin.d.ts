import type { Readable, Writable } from "node:stream";
import { Host } from "./host.js";
import type { ChannelHandler, CommandHandler, EventHandler, RouteHandler, ServiceHandler, TimerHandler, ToolGate, ToolHandler, UiHandler, WebhookHandler } from "./types.js";
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
export declare class Plugin {
    private readonly toolsMeta;
    private readonly toolHandlers;
    private readonly routeHandlers;
    private readonly eventHandlers;
    private readonly timerHandlers;
    private readonly uiHandlers;
    private readonly commandHandlers;
    private readonly serviceHandlers;
    private readonly channelHandlers;
    settings: Record<string, unknown>;
    granted: string[];
    pluginId: string;
    dataDir: string;
    tier: string;
    locale: string;
    host: Host;
    private transport;
    constructor();
    tool(nameOrOpts: string | ToolOptions, descriptionOrHandler: string | ToolHandler, inputSchemaOrHandler?: Record<string, unknown> | ToolHandler, gateOrHandler?: ToolGate | ToolHandler, handlerArg?: ToolHandler): this;
    route(name: string, handler: RouteHandler): this;
    on(family: string, handler: EventHandler): this;
    onEvent(family: string, handler: EventHandler): this;
    on_event(family: string, handler: EventHandler): this;
    timer(name: string, handler: TimerHandler): this;
    ui(surface: string, handler: UiHandler): this;
    webhook(hookName: string, handler: WebhookHandler): this;
    command(id: string, handler: CommandHandler): this;
    channel(name: string, handler: ChannelHandler): this;
    service(name: string, methodOrMap: string | Record<string, ServiceHandler>, handler?: ServiceHandler): this;
    handle(method: string, params?: Record<string, unknown>): Promise<unknown>;
    private _installConsoleRedirect;
    serve(opts?: ServeOptions): Promise<void>;
    private _serveOneshot;
    private _runSingleOneshotRequest;
    private _serveRpc;
}
