import { describe, expect, it } from "vitest";
import {
  API_VERSION,
  FrameLimitError,
  HostError,
  MAX_FRAME_BYTES,
  NdjsonSplitter,
  Plugin,
  RPC_ERROR_CODES,
  encodeFrame,
} from "@carnivore/plugin-sdk";
import { FakeHost, attach, renderUi } from "@carnivore/plugin-sdk/testing";

describe("Plugin & FakeHost", () => {
  it("handles initialize, ping, shutdown, tools, routes, events, timers, ui, webhooks, commands, and services", async () => {
    const eventsSeen: Array<{ seq: number | null | undefined; payload: unknown }> = [];
    const hooksSeen: Array<{ hook: string; payload: unknown }> = [];
    const timersSeen: number[] = [];

    const plugin = new Plugin()
      .tool(
        "echo",
        "Echoes text",
        { type: "object", properties: { msg: { type: "string" } } },
        "read",
        async (args, caller) => ({ echoed: args.msg, caller: caller.kind ?? "unknown" }),
      )
      .route("status", async (req) => ({ status: 200, body: { route: req.route, ok: true } }))
      .on("feed.meta", async (seq, payload) => {
        eventsSeen.push({ seq, payload });
      })
      .webhook("github", async (payload, _seq, meta) => {
        hooksSeen.push({ hook: meta.hook, payload });
      })
      .timer("tick", async (ts) => {
        timersSeen.push(ts);
      })
      .ui("widget", async (params) => ({
        schema: 1,
        root: { type: "text", value: `hi ${String(params.who ?? "world")}` },
      }))
      .command("refresh", async (params) => ({ refreshed: params.target ?? "all" }))
      .service("math", "add", async (args) => ({ sum: Number(args.a ?? 0) + Number(args.b ?? 0) }))
      .channel("ops", async (event, config) => ({
        ok: true,
        status_code: 202,
        detail: `${String(event.title ?? "")}:${String(config.dest ?? "")}`,
      }));

    const initRes = (await plugin.handle("initialize", {
      settings: { mode: "fast" },
      granted: ["sessions.read"],
      plugin_id: "demo",
      data_dir: "/tmp/demo",
    })) as {
      api_version: string;
      capabilities: Record<string, boolean>;
      subscriptions: string[];
    };

    expect(initRes.api_version).toBe(API_VERSION);
    expect(initRes.capabilities).toEqual({ tools: true, routes: true, events: true, timers: true, services: true });
    expect(initRes.subscriptions).toEqual(["feed.meta", "webhook.github"]);
    expect(plugin.settings).toEqual({ mode: "fast" });
    expect(plugin.granted).toEqual(["sessions.read"]);

    expect(await plugin.handle("ping", {})).toEqual({ ts: 0 });
    expect(await plugin.handle("shutdown", {})).toEqual({});

    const listed = (await plugin.handle("tools/list", {})) as { tools: Array<{ name: string }> };
    expect(listed.tools.map((t) => t.name)).toEqual(["echo"]);

    const called = (await plugin.handle("tools/call", {
      name: "echo",
      arguments: { msg: "yo" },
      caller: { kind: "owner" },
    })) as { content: Array<{ type: string; text: string }> };
    expect(JSON.parse(called.content[0].text)).toEqual({ echoed: "yo", caller: "owner" });

    expect(await plugin.handle("route.handle", { route: "status", method: "GET" })).toEqual({
      status: 200,
      body: { route: "status", ok: true },
    });

    await plugin.handle("event.deliver", { family: "feed.meta", seq: 7, payload: { n: 1 } });
    expect(eventsSeen).toEqual([{ seq: 7, payload: { n: 1 } }]);

    await plugin.handle("event.deliver", {
      family: "webhook.github",
      seq: 8,
      payload: { hook: "github", payload: { action: "opened" } },
    });
    expect(hooksSeen).toEqual([{ hook: "github", payload: { action: "opened" } }]);

    await plugin.handle("timer.tick", { name: "tick", scheduled_for: 12345 });
    expect(timersSeen).toEqual([12345]);

    expect(await renderUi(plugin, "widget", { who: "alice" })).toEqual({
      document: { schema: 1, root: { type: "text", value: "hi alice" } },
    });

    await expect(plugin.handle("ui.render", { surface: "missing", params: {} })).rejects.toMatchObject({
      code: RPC_ERROR_CODES.METHOD_NOT_FOUND,
    });

    expect(await plugin.handle("command.run", { command: "refresh", target: "ui" })).toEqual({
      refreshed: "ui",
    });
    expect(await plugin.handle("service.call", { service: "math", method: "add", args: { a: 2, b: 3 } })).toEqual({
      sum: 5,
    });
    expect(
      await plugin.handle("channel.send", {
        channel: "ops",
        event: { title: "Alert" },
        config: { dest: "room1" },
      }),
    ).toEqual({
      ok: true,
      status_code: 202,
      detail: "Alert:room1",
    });
    await expect(plugin.handle("channel.send", { channel: "missing", event: {}, config: {} })).rejects.toMatchObject({
      code: RPC_ERROR_CODES.METHOD_NOT_FOUND,
    });
  });

  it("wraps all 33 HostDispatcher RPC methods via FakeHost", async () => {
    const plugin = new Plugin();
    const fake = new FakeHost({
      "sessions.list": { sessions: [{ id: "ses_1" }] },
      "ai.call": { output: "hello from ai" },
      "storage.get": (p) => ({ value: `val:${String(p.key)}` }),
      "exports.write": { path: "/tmp/out.txt" },
      "ui.slot.publish": { slot: "session.badges", items: [{ id: "b1", badge: "OK" }] },
      "service.call": { answer: 42 },
      "events.emit": { delivered: 1 },
    });
    attach(plugin, fake);

    await plugin.host.sessions.list();
    await plugin.host.sessions.get("ses_1");
    await plugin.host.sessions.output("ses_1", 25);
    await plugin.host.sessions.permissionMode("ses_1");
    await plugin.host.sessions.message("ses_1", "hello", "tok_1");
    await plugin.host.sessions.create({ project: 1, prompt: "hi", family: "claude" });
    await plugin.host.sessions.control("ses_1", "wake");

    await plugin.host.notify.toast("ses_1", "Done");
    await plugin.host.notify.alert("build_done", "info", "Build complete", { n: 1 });

    await plugin.host.storage.put("k1", { ok: true });
    expect(await plugin.host.storage.get("k1")).toEqual({ value: "val:k1" });
    await plugin.host.storage.delete("k1");
    await plugin.host.storage.list("k");

    await plugin.host.topic.publish("updates", "k1");
    await plugin.host.ui.invalidate("widget");
    expect(await plugin.host.ui.slotPublish("session.badges", [{ id: "b1", badge: "OK" }])).toEqual({
      slot: "session.badges",
      items: [{ id: "b1", badge: "OK" }],
    });

    await plugin.host.httpFetch("https://api.github.com/zen", { method: "POST", json: { x: 1 } });
    expect(await plugin.host.aiCall("sum", "chat", { prompt: "hi" })).toBe("hello from ai");
    await plugin.host.ledgerRead();

    await plugin.host.projects.list();
    await plugin.host.projects.git(1, "status");
    await plugin.host.projects.snapshot(1, "turn-1");

    await plugin.host.exports.writeText("/exports", "report.txt", "hello");
    await plugin.host.log("info", "started", { step: 1 });
    await plugin.host.processSnapshot();
    await plugin.host.mcpConfig("ses_1");
    await plugin.host.mcpLinks("ses_1");

    await plugin.host.flowRun("42", { seed: "huddle_item", refresh: true });
    await plugin.host.flowRunPart("tok", 0);
    await plugin.host.flowFeed("42", "updates", { cursor: 10 });
    await plugin.host.flowTasks("bug", 10);

    expect(await plugin.host.service.call("other", "ping", { n: 1 })).toEqual({ answer: 42 });
    expect(await plugin.host.events.emit("demo.ready", { ok: true })).toEqual({ delivered: 1 });

    const seenMethods = new Set(fake.calls.map((c) => c.method));
    expect(seenMethods.size).toBe(33);

    const exportCall = fake.calls.find((c) => c.method === "exports.write");
    expect(exportCall?.params.bytes).toBe(Buffer.from("hello", "utf8").toString("base64"));

    const errFake = new FakeHost({
      "sessions.list": new HostError(RPC_ERROR_CODES.NOT_GRANTED, "not_granted", {
        permission: "sessions.read",
      }),
    });
    attach(plugin, errFake);
    await expect(plugin.host.sessions.list()).rejects.toMatchObject({
      code: RPC_ERROR_CODES.NOT_GRANTED,
      reason: "not_granted",
    });
  });

  it("enforces NDJSON framing limits on split and oversized frames", () => {
    const splitter = new NdjsonSplitter(64);
    expect(splitter.feed('{"a":1}\n{"b":')).toEqual(['{"a":1}']);
    expect(splitter.feed('2}\n\n')).toEqual(['{"b":2}']);

    expect(() => splitter.feed("x".repeat(65))).toThrow(FrameLimitError);
    expect(() => encodeFrame({ big: "a".repeat(MAX_FRAME_BYTES) })).toThrow(FrameLimitError);
  });
});
