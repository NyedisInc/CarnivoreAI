import type { HostErrorData, JsonRpcResponse } from "./types.js";
export declare const API_VERSION = "1.0";
export declare const MAX_FRAME_BYTES: number;
export declare const MAX_NESTING = 32;
export declare const RPC_ERROR_CODES: {
    readonly PERMISSION_DENIED: -32001;
    readonly NOT_GRANTED: -32002;
    readonly DIALOG_OPEN: -32003;
    readonly RATE_LIMITED: -32004;
    readonly TOO_LARGE: -32005;
    readonly TIMEOUT: -32006;
    readonly DISABLED: -32007;
    readonly INVALID_REQUEST: -32600;
    readonly METHOD_NOT_FOUND: -32601;
    readonly INVALID_PARAMS: -32602;
    readonly INTERNAL_ERROR: -32603;
};
export declare class HostError extends Error {
    readonly code: number;
    readonly reason: string;
    readonly data: HostErrorData;
    constructor(code: number, reason: string, data?: HostErrorData);
}
export declare class RpcMethodError extends Error {
    readonly code: number;
    constructor(code: number, message: string);
}
export declare class FrameLimitError extends Error {
    readonly code: string;
    constructor(code: string, message: string);
}
export declare function checkNesting(value: unknown, limit?: number): boolean;
export declare class NdjsonSplitter {
    private readonly limit;
    private buf;
    constructor(limit?: number);
    feed(chunk: Buffer | Uint8Array | string): string[];
}
export declare function encodeFrame(message: Record<string, unknown>): string;
export declare class RpcClientTransport {
    private nextId;
    private readonly pending;
    private readonly writeLine;
    constructor(writeLine: (line: string) => void);
    request(method: string, params?: Record<string, unknown>, timeoutMs?: number): Promise<unknown>;
    notify(method: string, params?: Record<string, unknown>): void;
    handleResponse(frame: JsonRpcResponse): boolean;
    rejectAll(err: Error): void;
}
