import { sanitizeRects, type Rect } from './hit-regions';

export const VERBS = ['route.call', 'tool.call', 'ui.state', 'overlay.hit_regions'] as const;
export type Verb = (typeof VERBS)[number];

export interface Declared {
    readonly routes: readonly string[];
    readonly tools: readonly string[];
}

export interface InboundMessage {
    readonly source: unknown;
    readonly data: unknown;
}

export interface BridgeOptions {
    readonly nonce: string;
    readonly frame: () => { postMessage: (message: unknown, targetOrigin: string) => void } | null;
    readonly declared: Declared;
    readonly callRoute: (route: string, payload: unknown) => Promise<unknown>;
    readonly viewport: () => { w: number; h: number };
    readonly onState?: (state: string) => void;
    readonly onHitRegions?: (rects: Rect[]) => void;
    readonly onReload?: () => void;
}

const MAX_PAYLOAD_CHARS = 16_384;
const STATE_WORD = /^[a-z][a-z_]{0,23}$/;
const MAX_ID_CHARS = 64;

export function newNonce(): string {
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function createBridge(options: BridgeOptions): { handle: (event: InboundMessage) => void; init: () => void } {
    let loads = 0;
    let dropped = false;
    const reply = (id: unknown, body: Record<string, unknown>): void => {
        if (dropped) return;
        options.frame()?.postMessage({ nonce: options.nonce, id, ...body }, '*');
    };

    const run = async (verb: 'route.call' | 'tool.call', msg: Record<string, unknown>, id: unknown): Promise<void> => {
        const name = verb === 'route.call' ? msg.route : msg.tool;
        const known = verb === 'route.call' ? options.declared.routes : options.declared.tools;
        if (typeof name !== 'string' || !known.includes(name)) return reply(id, { ok: false, error: 'undeclared' });
        if (verb === 'tool.call') return reply(id, { ok: false, error: 'tool_action_unavailable' });
        let payload: unknown = msg.payload ?? {};
        try {
            if (JSON.stringify(payload).length > MAX_PAYLOAD_CHARS) return reply(id, { ok: false, error: 'payload_too_large' });
            payload = JSON.parse(JSON.stringify(payload));
        } catch {
            return reply(id, { ok: false, error: 'payload_not_json' });
        }
        try {
            reply(id, { ok: true, result: await options.callRoute(name, payload) });
        } catch (error) {
            reply(id, { ok: false, error: (error as { code?: unknown } | null)?.code === 'rate_limited' ? 'rate_limited' : 'failed' });
        }
    };

    return {
        handle(event: InboundMessage): void {
            const frame = options.frame();
            if (dropped || !frame || event.source !== frame) return;
            const msg = event.data;
            if (typeof msg !== 'object' || msg === null || Array.isArray(msg)) return;
            const m = msg as Record<string, unknown>;
            if (typeof m.nonce !== 'string' || m.nonce !== options.nonce) return;
            if (typeof m.verb !== 'string' || !(VERBS as readonly string[]).includes(m.verb)) return;
            const id = typeof m.id === 'string' && m.id.length <= MAX_ID_CHARS ? m.id : typeof m.id === 'number' ? m.id : null;
            switch (m.verb as Verb) {
                case 'route.call':
                case 'tool.call':
                    void run(m.verb as 'route.call' | 'tool.call', m, id);
                    return;
                case 'ui.state':
                    if (typeof m.state === 'string' && STATE_WORD.test(m.state)) options.onState?.(m.state);
                    return;
                case 'overlay.hit_regions':
                    options.onHitRegions?.(sanitizeRects(m.rects, options.viewport()));
                    return;
            }
        },
        init(): void {
            loads++;
            if (loads > 1) {
                if (!dropped) {
                    dropped = true;
                    options.onReload?.();
                }
                return;
            }
            options.frame()?.postMessage({ verb: 'init', nonce: options.nonce }, '*');
        },
    };
}
