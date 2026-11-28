import type { HostErrorData, JsonRpcError, JsonRpcResponse } from "./types.js";

export const API_VERSION = "1.0";
export const MAX_FRAME_BYTES = 1024 * 1024;
export const MAX_NESTING = 32;

export const RPC_ERROR_CODES = {
  PERMISSION_DENIED: -32001,
  NOT_GRANTED: -32002,
  DIALOG_OPEN: -32003,
  RATE_LIMITED: -32004,
  TOO_LARGE: -32005,
  TIMEOUT: -32006,
  DISABLED: -32007,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL_ERROR: -32603,
} as const;

export class HostError extends Error {
  readonly code: number;
  readonly reason: string;
  readonly data: HostErrorData;

  constructor(code: number, reason: string, data?: HostErrorData) {
    super(`${code} ${reason}`);
    this.name = "HostError";
    this.code = code;
    this.reason = reason;
    this.data = data ?? {};
  }
}

export class RpcMethodError extends Error {
  readonly code: number;

  constructor(code: number, message: string) {
    super(message);
    this.name = "RpcMethodError";
    this.code = code;
  }
}

export class FrameLimitError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "FrameLimitError";
    this.code = code;
  }
}

export function checkNesting(value: unknown, limit = MAX_NESTING): boolean {
  const stack: Array<[unknown, number]> = [[value, 1]];
  while (stack.length > 0) {
    const [item, level] = stack.pop()!;
    if (level > limit) {
      return false;
    }
    if (item !== null && typeof item === "object") {
      if (Array.isArray(item)) {
        for (const v of item) {
          stack.push([v, level + 1]);
        }
      } else {
        for (const v of Object.values(item as Record<string, unknown>)) {
          stack.push([v, level + 1]);
        }
      }
    }
  }
  return true;
}

export class NdjsonSplitter {
  private readonly limit: number;
  private buf: Buffer = Buffer.alloc(0);

  constructor(limit = MAX_FRAME_BYTES) {
    this.limit = limit;
  }

  feed(chunk: Buffer | Uint8Array | string): string[] {
    const incoming = typeof chunk === "string" ? Buffer.from(chunk, "utf8") : Buffer.from(chunk);
    this.buf = this.buf.length === 0 ? incoming : Buffer.concat([this.buf, incoming]);
    const lines: string[] = [];
    while (true) {
      const nl = this.buf.indexOf(0x0a);
      if (nl < 0) {
        if (this.buf.length > this.limit) {
          throw new FrameLimitError("frame_too_large", `no newline within ${this.limit} bytes`);
        }
        return lines;
      }
      if (nl > this.limit) {
        throw new FrameLimitError("frame_too_large", `line of ${nl} bytes`);
      }
      const line = this.buf.subarray(0, nl).toString("utf8").trim();
      this.buf = this.buf.subarray(nl + 1);
      if (line.length > 0) {
        lines.push(line);
      }
    }
  }
}

export function encodeFrame(message: Record<string, unknown>): string {
  const payload = JSON.stringify({ jsonrpc: "2.0", ...message });
  const byteLen = Buffer.byteLength(payload, "utf8");
  if (byteLen > MAX_FRAME_BYTES) {
    throw new FrameLimitError("frame_too_large", `outgoing frame is ${byteLen} bytes (max ${MAX_FRAME_BYTES})`);
  }
  return `${payload}\n`;
}

interface PendingCall {
  resolve: (value: unknown) => void;
  reject: (err: Error) => void;
  timer?: ReturnType<typeof setTimeout>;
}

export class RpcClientTransport {
  private nextId = 0;
  private readonly pending = new Map<number, PendingCall>();
  private readonly writeLine: (line: string) => void;

  constructor(writeLine: (line: string) => void) {
    this.writeLine = writeLine;
  }

  request(method: string, params: Record<string, unknown> = {}, timeoutMs?: number): Promise<unknown> {
    this.nextId += 1;
    const rid = this.nextId;
    const encoded = encodeFrame({ id: rid, method, params });
    return new Promise((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      if (timeoutMs !== undefined && timeoutMs > 0) {
        timer = setTimeout(() => {
          const entry = this.pending.get(rid);
          if (entry) {
            this.pending.delete(rid);
            reject(new HostError(RPC_ERROR_CODES.TIMEOUT, "timeout", { reason: "timeout" }));
          }
        }, timeoutMs);
      }
      this.pending.set(rid, { resolve, reject, timer });
      try {
        this.writeLine(encoded);
      } catch (err) {
        if (timer) {
          clearTimeout(timer);
        }
        this.pending.delete(rid);
        reject(err instanceof Error ? err : new Error(String(err)));
      }
    });
  }

  notify(method: string, params: Record<string, unknown> = {}): void {
    const encoded = encodeFrame({ method, params });
    this.writeLine(encoded);
  }

  handleResponse(frame: JsonRpcResponse): boolean {
    const entry = this.pending.get(frame.id);
    if (!entry) {
      return false;
    }
    this.pending.delete(frame.id);
    if (entry.timer) {
      clearTimeout(entry.timer);
    }
    if (frame.error) {
      const err: JsonRpcError = frame.error;
      entry.reject(new HostError(err.code ?? 0, err.message ?? "error", err.data));
    } else {
      entry.resolve(frame.result);
    }
    return true;
  }

  rejectAll(err: Error): void {
    for (const [rid, entry] of this.pending.entries()) {
      this.pending.delete(rid);
      if (entry.timer) {
        clearTimeout(entry.timer);
      }
      entry.reject(err);
    }
  }
}
