import { HostError } from "./frames.js";
import { Host } from "./host.js";
import type { Plugin } from "./plugin.js";
import type { RpcSender } from "./types.js";

export type FakeResponse = unknown | ((params: Record<string, unknown>) => unknown);

export interface RecordedCall {
  method: string;
  params: Record<string, unknown>;
}

export class FakeHost {
  readonly responses: Record<string, FakeResponse>;
  readonly calls: RecordedCall[] = [];

  constructor(responses: Record<string, FakeResponse> = {}) {
    this.responses = { ...responses };
  }

  readonly send: RpcSender = async (method: string, params: Record<string, unknown>): Promise<unknown> => {
    this.calls.push({ method, params });
    const answer = this.responses[method];
    if (answer instanceof HostError) {
      throw answer;
    }
    if (typeof answer === "function") {
      const out = await (answer as (p: Record<string, unknown>) => unknown)(params);
      if (out instanceof HostError) {
        throw out;
      }
      return out;
    }
    return answer ?? {};
  };
}

export function attach(plugin: Plugin, fakeHost: FakeHost): Plugin {
  plugin.host = new Host(fakeHost.send);
  return plugin;
}

export async function renderUi(
  plugin: Plugin,
  surface: string,
  params: Record<string, unknown> = {},
): Promise<unknown> {
  return await plugin.handle("ui.render", { surface, params });
}
