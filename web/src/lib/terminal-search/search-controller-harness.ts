import { SearchController } from './search-controller.svelte';
import type { SearchHost } from './search-host';
import type { BufferLike, EngineResults, ScannedPrompt } from './types';

export interface Calls {
    attach: unknown[];
    find: Array<[string, string]>;
    next: number;
    prev: number;
    clear: number;
    predicate: string[];
    history: Array<string | null>;
    focusTerm: number;
    clearSelection: number;
}

export interface World {
    sessionId: string | null;
    bufferType: string;
    screenActive: boolean;
    modalDepth: number;
    withHistory: boolean;
    historyResult: { loaded?: 'painted' | 'already' | 'unavailable' } | Error;
    onResults: null | ((r: EngineResults) => void);
    agentFamily: string | null;
    scannedPrompts: ScannedPrompt[];
}

export function harness(patch: Partial<World> = {}) {
    const world: World = {
        sessionId: 'ses_a',
        bufferType: 'normal',
        screenActive: true,
        modalDepth: 0,
        withHistory: true,
        historyResult: { loaded: 'painted' },
        onResults: null,
        agentFamily: 'claude',
        scannedPrompts: [],
        ...patch,
    };
    const calls: Calls = {
        attach: [],
        find: [],
        next: 0,
        prev: 0,
        clear: 0,
        predicate: [],
        history: [],
        focusTerm: 0,
        clearSelection: 0,
    };
    const buffer: BufferLike = { baseY: 0, cursorY: 0, viewportY: 0, length: 10 };
    const term = {
        cols: 80,
        rows: 24,
        get buffer() {
            return { active: { ...buffer, type: world.bufferType } };
        },
        registerMarker: () => null,
        scrollToLine: () => {},
        clearSelection: () => {
            calls.clearSelection += 1;
        },
    };
    const host: SearchHost = {
        term: () => term,
        sessionId: () => world.sessionId,
        onTerminal: () => () => {},
        agentFamily: () => world.agentFamily,
        engine: () => ({
            attach: (t) => calls.attach.push(t),
            find: (q, _o, dir) => calls.find.push([q, dir]),
            next: () => {
                calls.next += 1;
            },
            prev: () => {
                calls.prev += 1;
            },
            clear: () => {
                calls.clear += 1;
            },
            onResults: (cb) => {
                world.onResults = cb;
                return () => {
                    world.onResults = null;
                };
            },
            predicate: (q) => {
                calls.predicate.push(q);
                return (text: string) => text.includes(q);
            },
        }),
        history: () =>
            world.withHistory
                ? {
                    ensureLoaded: (_t, id) => {
                        calls.history.push(id);
                        return world.historyResult instanceof Error
                            ? Promise.reject(world.historyResult)
                            : Promise.resolve(world.historyResult);
                    },
                }
                : null,
        promptScan: () => ({
            scan: () => world.scannedPrompts,
            layoutTicks: () => [],
            currentOrdinalFor: () => 0,
        }),
        isRule: () => undefined,
        modalOpen: () => world.modalDepth > 0,
        terminalScreenActive: () => world.screenActive,
        focusTerm: () => {
            calls.focusTerm += 1;
        },
    };
    return { calls, world, host, controller: new SearchController(host) };
}

export async function settle(): Promise<void> {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
}
