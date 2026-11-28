import { Host } from "./host.js";
export interface SocketHostOptions {
    timeoutMs?: number;
}
export declare class SocketHost {
    readonly path: string;
    readonly host: Host;
    private readonly socket;
    private readonly transport;
    private readonly splitter;
    private readonly timeoutMs?;
    private closed;
    private constructor();
    static connect(sockPath?: string, opts?: SocketHostOptions): Promise<SocketHost>;
    call(method: string, params?: Record<string, unknown>, timeoutMs?: number): Promise<unknown>;
    notify(method: string, params?: Record<string, unknown>): void;
    close(): void;
}
export declare function connectSocket(sockPath?: string, opts?: SocketHostOptions): Promise<SocketHost>;
