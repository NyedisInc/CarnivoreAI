import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { PassThrough } from "node:stream";
import { describe, expect, it } from "vitest";

import { HostError, Plugin, connectSocket } from "@carnivore/plugin-sdk";

describe("Plugin.serve & SocketHost", () => {
  it("serves bidirectional stdio RPC and redirects console.log away from stdout", async () => {
    const plugin = new Plugin().tool("list_it", "Lists sessions", async () => {
      console.log("debug noise should go to stderr");
      const res = await plugin.host.sessions.list();
      return { count: res.sessions.length };
    });

    const input = new PassThrough();
    const output = new PassThrough();
    const outLines: Array<Record<string, unknown>> = [];
    let buf = "";

    const origErr = console.error;
    const errSeen: unknown[] = [];
    console.error = (...args: unknown[]) => {
      errSeen.push(args.join(" "));
    };

    output.on("data", (chunk: Buffer) => {
      buf += chunk.toString("utf8");
      while (buf.includes("\n")) {
        const idx = buf.indexOf("\n");
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        if (!line) continue;
        const msg = JSON.parse(line) as Record<string, unknown>;
        outLines.push(msg);
        if (msg.method === "sessions.list") {
          input.write(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { sessions: [{ id: "s1" }] } }) + "\n");
        }
      }
    });

    const serveDone = plugin.serve({ input, output, mode: "rpc" });

    input.write(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { settings: {}, granted: ["sessions.read"] } }) + "\n");
    input.write(JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "list_it", arguments: {} } }) + "\n");

    await new Promise<void>((resolve) => {
      const check = () => {
        if (outLines.some((m) => m.id === 2 && "result" in m)) {
          resolve();
        } else {
          setTimeout(check, 5);
        }
      };
      check();
    });

    input.end();
    await serveDone;
    console.error = origErr;

    const toolReply = outLines.find((m) => m.id === 2) as { result: { content: Array<{ text: string }> } };
    expect(JSON.parse(toolReply.result.content[0].text)).toEqual({ count: 1 });
    expect(errSeen.some((s) => String(s).includes("debug noise"))).toBe(true);
  });

  it("connects SocketHost to an AF_UNIX socket and serves oneshot mode via $CARNIVORE_PLUGIN_SOCK", async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "carnivore-ts-sock-"));
    const sockPath = path.join(tmpDir, "p.sock");
    const seenIds: number[] = [];

    const server = net.createServer((conn) => {
      let buf = "";
      conn.on("data", (chunk) => {
        buf += chunk.toString("utf8");
        while (buf.includes("\n")) {
          const idx = buf.indexOf("\n");
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 1);
          if (!line) continue;
          const req = JSON.parse(line) as { id: number; method: string };
          seenIds.push(req.id);
          if (req.method === "fail.test") {
            conn.write(
              JSON.stringify({
                jsonrpc: "2.0",
                id: req.id,
                error: { code: -32002, message: "not_granted", data: { permission: "notify" } },
              }) + "\n",
            );
          } else {
            conn.write(JSON.stringify({ jsonrpc: "2.0", id: req.id, result: { projects: [{ id: 1, name: "demo" }] } }) + "\n");
          }
        }
      });
    });

    await new Promise<void>((resolve) => server.listen(sockPath, resolve));
    try {
      const sock = await connectSocket(sockPath);
      expect(await sock.host.projects.list()).toEqual({ projects: [{ id: 1, name: "demo" }] });
      await expect(sock.call("fail.test", {})).rejects.toBeInstanceOf(HostError);
      sock.close();
      expect(seenIds).toEqual([1, 2]);

      const plugin = new Plugin().tool("proj", "Lists projects", async () => {
        const res = await plugin.host.projects.list();
        return { count: res.projects.length };
      });
      const input = new PassThrough();
      const output = new PassThrough();
      const chunks: Buffer[] = [];
      output.on("data", (c: Buffer) => chunks.push(c));

      const serving = plugin.serve({ input, output, mode: "oneshot", sockPath });
      input.end(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "proj", arguments: {} } }) + "\n");
      await serving;

      const reply = JSON.parse(Buffer.concat(chunks).toString("utf8").trim()) as {
        id: number;
        result: { content: Array<{ text: string }> };
      };
      expect(reply.id).toBe(1);
      expect(JSON.parse(reply.result.content[0].text)).toEqual({ count: 1 });

      seenIds.length = 0;
      const concurrentPlugin = new Plugin().tool("multi", "Calls host concurrently", async () => {
        const [a, b] = await Promise.all([
          concurrentPlugin.host.projects.list(),
          concurrentPlugin.host.projects.list(),
        ]);
        return { a: a.projects.length, b: b.projects.length };
      });
      const cIn = new PassThrough();
      const cOut = new PassThrough();
      const cChunks: Buffer[] = [];
      cOut.on("data", (c: Buffer) => cChunks.push(c));
      const cServing = concurrentPlugin.serve({ input: cIn, output: cOut, mode: "oneshot", sockPath });
      cIn.end(JSON.stringify({ jsonrpc: "2.0", id: 7, method: "tools/call", params: { name: "multi", arguments: {} } }) + "\n");
      await cServing;
      const cReply = JSON.parse(Buffer.concat(cChunks).toString("utf8").trim()) as {
        id: number;
        result: { content: Array<{ text: string }> };
      };
      expect(cReply.id).toBe(7);
      expect(JSON.parse(cReply.result.content[0].text)).toEqual({ a: 1, b: 1 });
      expect(seenIds).toEqual([1, 2]);
    } finally {
      server.close();
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("redirects console.debug, dir, table, count, and timeEnd to stderr and restores them", async () => {
    const plugin = new Plugin().tool("noisy", "Emits various console methods", async () => {
      console.debug("dbg-line");
      console.dir({ dirKey: 1 });
      console.table([{ a: 1 }]);
      console.count("cnt");
      console.timeEnd("tm");
      return "ok";
    });
    const input = new PassThrough();
    const output = new PassThrough();
    const outChunks: Buffer[] = [];
    output.on("data", (c: Buffer) => outChunks.push(c));

    const origErr = console.error;
    const origDebug = console.debug;
    const origDir = console.dir;
    const errSeen: string[] = [];
    console.error = (...args: unknown[]) => {
      errSeen.push(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
    };

    try {
      const serving = plugin.serve({ input, output, mode: "oneshot" });
      input.end(JSON.stringify({ jsonrpc: "2.0", id: 9, method: "tools/call", params: { name: "noisy", arguments: {} } }) + "\n");
      await serving;
      const line = Buffer.concat(outChunks).toString("utf8").trim();
      const parsed = JSON.parse(line) as { id: number; result: { content: Array<{ text: string }> } };
      expect(parsed.id).toBe(9);
      expect(parsed.result.content[0].text).toBe("ok");
      expect(errSeen.some((s) => s.includes("dbg-line"))).toBe(true);
      expect(errSeen.length).toBeGreaterThanOrEqual(5);
      expect(console.debug).toBe(origDebug);
      expect(console.dir).toBe(origDir);
    } finally {
      console.error = origErr;
    }
  });

  it("isolates and propagates _bus_token concurrently via AsyncLocalStorage in RPC mode and via env in oneshot/SocketHost", async () => {
    const plugin = new Plugin().service("chain", "step", async (args) => {
      const waitMs = Number(args.delay ?? 0);
      if (waitMs > 0) {
        await new Promise((r) => setTimeout(r, waitMs));
      }
      return await plugin.host.service.call("downstream", "echo", { tag: args.tag });
    });

    const input = new PassThrough();
    const output = new PassThrough();
    const outFrames: Array<Record<string, unknown>> = [];
    let buf = "";

    output.on("data", (chunk: Buffer) => {
      buf += chunk.toString("utf8");
      while (buf.includes("\n")) {
        const idx = buf.indexOf("\n");
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        if (!line) continue;
        const msg = JSON.parse(line) as Record<string, unknown>;
        outFrames.push(msg);
        if (msg.method === "service.call") {
          const p = msg.params as Record<string, unknown>;
          input.write(
            JSON.stringify({
              jsonrpc: "2.0",
              id: msg.id,
              result: { seen_token: p._bus_token ?? null, tag: (p.args as Record<string, unknown>)?.tag },
            }) + "\n",
          );
        }
      }
    });

    const serveDone = plugin.serve({ input, output, mode: "rpc" });
    input.write(
      JSON.stringify({
        jsonrpc: "2.0",
        id: 10,
        method: "service.call",
        params: { service: "chain", method: "step", args: { tag: "slow", delay: 25 }, _bus_token: "tok-slow" },
      }) + "\n",
    );
    input.write(
      JSON.stringify({
        jsonrpc: "2.0",
        id: 11,
        method: "service.call",
        params: { service: "chain", method: "step", args: { tag: "fast", delay: 0 }, _bus_token: "tok-fast" },
      }) + "\n",
    );

    await new Promise<void>((resolve) => {
      const check = () => {
        if (outFrames.some((m) => m.id === 10 && "result" in m) && outFrames.some((m) => m.id === 11 && "result" in m)) {
          resolve();
        } else {
          setTimeout(check, 5);
        }
      };
      check();
    });
    input.end();
    await serveDone;

    const r10 = outFrames.find((m) => m.id === 10)?.result as { seen_token: string; tag: string };
    const r11 = outFrames.find((m) => m.id === 11)?.result as { seen_token: string; tag: string };
    expect(r10).toEqual({ seen_token: "tok-slow", tag: "slow" });
    expect(r11).toEqual({ seen_token: "tok-fast", tag: "fast" });

    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "carnivore-ts-bustok-"));
    const sockPath = path.join(tmpDir, "b.sock");
    const seenBusTokens: Array<string | undefined> = [];
    const server = net.createServer((conn) => {
      let sBuf = "";
      conn.on("data", (chunk) => {
        sBuf += chunk.toString("utf8");
        while (sBuf.includes("\n")) {
          const idx = sBuf.indexOf("\n");
          const line = sBuf.slice(0, idx).trim();
          sBuf = sBuf.slice(idx + 1);
          if (!line) continue;
          const req = JSON.parse(line) as { id: number; method: string; params: Record<string, unknown> };
          seenBusTokens.push(req.params._bus_token as string | undefined);
          conn.write(JSON.stringify({ jsonrpc: "2.0", id: req.id, result: { token: req.params._bus_token ?? null } }) + "\n");
        }
      });
    });

    await new Promise<void>((resolve) => server.listen(sockPath, resolve));
    const prevTok = process.env.CARNIVORE_BUS_TOKEN;
    try {
      process.env.CARNIVORE_BUS_TOKEN = "env-tok-123";
      const sock = await connectSocket(sockPath);
      expect(await sock.host.service.call("downstream", "ping", {})).toEqual({ token: "env-tok-123" });
      sock.close();

      const oneIn = new PassThrough();
      const oneOut = new PassThrough();
      const oneChunks: Buffer[] = [];
      oneOut.on("data", (c: Buffer) => oneChunks.push(c));
      const oneDone = plugin.serve({ input: oneIn, output: oneOut, mode: "oneshot", sockPath });
      oneIn.end(
        JSON.stringify({
          jsonrpc: "2.0",
          id: 99,
          method: "service.call",
          params: { service: "chain", method: "step", args: { tag: "one" }, _bus_token: "frame-tok-99" },
        }) + "\n",
      );
      await oneDone;
      const oneReply = JSON.parse(Buffer.concat(oneChunks).toString("utf8").trim()) as {
        id: number;
        result: { token: string };
      };
      expect(oneReply.result).toEqual({ token: "frame-tok-99" });
      expect(seenBusTokens).toEqual(["env-tok-123", "frame-tok-99"]);
    } finally {
      if (prevTok === undefined) {
        delete process.env.CARNIVORE_BUS_TOKEN;
      } else {
        process.env.CARNIVORE_BUS_TOKEN = prevTok;
      }
      server.close();
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
