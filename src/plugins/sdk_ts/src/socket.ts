import net from "node:net";

import { NdjsonSplitter, RpcClientTransport } from "./frames.js";
import { Host } from "./host.js";
import type { JsonRpcResponse } from "./types.js";

export interface SocketHostOptions {
  timeoutMs?: number;
}

export class SocketHost {
  readonly path: string;
  readonly host: Host;
  private readonly socket: net.Socket;
  private readonly transport: RpcClientTransport;
  private readonly splitter = new NdjsonSplitter();
  private readonly timeoutMs?: number;
  private closed = false;

  private constructor(sockPath: string, socket: net.Socket, opts: SocketHostOptions) {
    this.path = sockPath;
    this.socket = socket;
    this.timeoutMs = opts.timeoutMs;
    this.transport = new RpcClientTransport((line) => {
      if (this.closed) {
        throw new Error("socket host is closed");
      }
      this.socket.write(line);
    });
    this.host = new Host((method, params) => this.call(method, params));

    this.socket.on("data", (chunk) => {
      try {
        for (const line of this.splitter.feed(chunk)) {
          const parsed = JSON.parse(line) as JsonRpcResponse;
          if (parsed && typeof parsed === "object" && typeof parsed.id === "number") {
            this.transport.handleResponse(parsed);
          }
        }
      } catch (err) {
        this.transport.rejectAll(err instanceof Error ? err : new Error(String(err)));
        this.close();
      }
    });

    this.socket.on("error", (err) => {
      this.transport.rejectAll(err);
    });

    this.socket.on("close", () => {
      this.closed = true;
      this.transport.rejectAll(new Error("socket closed"));
    });
  }

  static connect(sockPath?: string, opts: SocketHostOptions = {}): Promise<SocketHost> {
    const resolved = (sockPath ?? process.env.CARNIVORE_PLUGIN_SOCK ?? "").trim();
    if (!resolved) {
      return Promise.reject(new Error("CARNIVORE_PLUGIN_SOCK is not set"));
    }
    return new Promise((resolve, reject) => {
      const sock = net.createConnection({ path: resolved });
      const onError = (err: Error) => {
        sock.destroy();
        reject(err);
      };
      sock.once("error", onError);
      sock.once("connect", () => {
        sock.removeListener("error", onError);
        resolve(new SocketHost(resolved, sock, opts));
      });
    });
  }

  call(method: string, params: Record<string, unknown> = {}, timeoutMs?: number): Promise<unknown> {
    let wireParams = params;
    if (method === "service.call" && !("_bus_token" in params)) {
      const tok = process.env.CARNIVORE_BUS_TOKEN?.trim();
      if (tok) {
        wireParams = { ...params, _bus_token: tok };
      }
    }
    return this.transport.request(method, wireParams, timeoutMs ?? this.timeoutMs);
  }

  notify(method: string, params: Record<string, unknown> = {}): void {
    this.transport.notify(method, params);
  }

  close(): void {
    if (!this.closed) {
      this.closed = true;
      this.socket.end();
      this.socket.destroy();
    }
  }
}

export function connectSocket(sockPath?: string, opts: SocketHostOptions = {}): Promise<SocketHost> {
  return SocketHost.connect(sockPath, opts);
}
