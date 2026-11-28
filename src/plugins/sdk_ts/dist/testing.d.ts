import type { Plugin } from "./plugin.js";
import type { RpcSender } from "./types.js";
export type FakeResponse = unknown | ((params: Record<string, unknown>) => unknown);
export interface RecordedCall {
    method: string;
    params: Record<string, unknown>;
}
export declare class FakeHost {
    readonly responses: Record<string, FakeResponse>;
    readonly calls: RecordedCall[];
    constructor(responses?: Record<string, FakeResponse>);
    readonly send: RpcSender;
}
export declare function attach(plugin: Plugin, fakeHost: FakeHost): Plugin;
export declare function renderUi(plugin: Plugin, surface: string, params?: Record<string, unknown>): Promise<unknown>;
