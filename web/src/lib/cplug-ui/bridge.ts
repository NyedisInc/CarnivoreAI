import { sanitizeRects, type Rect } from './hit-regions';
import { cleanActions, type ViewAction } from './view-actions';

export const VERBS = ['route.call', 'tool.call', 'ui.state', 'overlay.hit_regions', 'ui.share', 'ui.actions', 'ui.menu'] as const;
export type Verb = (typeof VERBS)[number];

export interface Declared {
    readonly routes: readonly string[];
    readonly tools: readonly string[];
}

export interface InboundMessage {
    readonly source: unknown;
    readonly data: unknown;
}

export type ViewRole = 'panel' | 'menu' | 'page' | 'overlay';

export interface BridgeOptions {
    readonly nonce: string;
    readonly role?: ViewRole;
    readonly features?: () => readonly string[];
    readonly theme?: () => Readonly<Record<string, string>>;
    readonly frame: () => { postMessage: (message: unknown, targetOrigin: string) => void } | null;
    readonly declared: Declared;
    readonly callRoute: (route: string, payload: unknown) => Promise<unknown>;
    readonly viewport: () => { w: number; h: number };
    readonly onState?: (state: string) => void;
    readonly onHitRegions?: (rects: Rect[]) => void;
    readonly onShare?: (value: unknown, show: boolean) => { ok: true } | { ok: false; error: string };
    readonly onActions?: (actions: ViewAction[]) => { ok: true } | { ok: false; error: string };
    readonly onMenu?: (at: { x: number; y: number } | null) => void;
    readonly label?: string;
    readonly onReload?: () => void;
    readonly visible?: () => boolean;
}

export const MAX_HELD_CALLS = 8;

const MAX_PAYLOAD_CHARS = 16_384;
const STATE_WORD = /^[a-z][a-z_]{0,23}$/;
const MAX_ID_CHARS = 64;

export function newNonce(): string {
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function createBridge(options: BridgeOptions): { handle: (event: InboundMessage) => void; init: () => void; release: () => void; send: (verb: string, body?: Record<string, unknown>) => void } {
    let loads = 0;
    let dropped = false;
    const reply = (id: unknown, body: Record<string, unknown>): void => {
        if (dropped) return;
        options.frame()?.postMessage({ nonce: options.nonce, id, ...body }, '*');
    };

    const held: Array<() => Promise<void>> = [];

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
        const send = async (): Promise<void> => {
            try {
                reply(id, { ok: true, result: await options.callRoute(name, payload) });
            } catch (error) {
                reply(id, { ok: false, error: (error as { code?: unknown } | null)?.code === 'rate_limited' ? 'rate_limited' : 'failed' });
            }
        };
        if (options.visible && !options.visible()) {
            if (held.length >= MAX_HELD_CALLS) return reply(id, { ok: false, error: 'rate_limited' });
            held.push(send);
            return;
        }
        await send();
    };

    let ready = false;
    return {
        release(): void {
            if (dropped || (options.visible && !options.visible())) return;
            const waiting = held.splice(0);
            for (const send of waiting) void send();
        },
        send(verb: string, body: Record<string, unknown> = {}): void {
            if (dropped || !ready) return;
            options.frame()?.postMessage({ ...body, verb, nonce: options.nonce }, '*');
        },
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
                case 'ui.share': {
                    const shared = options.onShare?.(m.value, m.show === true) ?? { ok: false, error: 'unavailable' };
                    reply(id, shared);
                    return;
                }
                case 'ui.actions': {
                    const clean = cleanActions(m);
                    if (!clean.ok) {
                        console.warn('cplug view bridge: ui.actions refused', { view: options.label, error: clean.error });
                        return reply(id, clean);
                    }
                    return reply(id, options.onActions?.(clean.actions) ?? { ok: false, error: 'unavailable' });
                }
                case 'ui.menu': {
                    const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
                    if (m.x === undefined && m.y === undefined) options.onMenu?.(null);
                    else if (finite(m.x) && finite(m.y)) options.onMenu?.({ x: m.x, y: m.y });
                    else console.warn('cplug view bridge: ui.menu refused', { view: options.label, error: 'invalid_point' });
                    return;
                }
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
                    held.length = 0;
                    options.onReload?.();
                }
                return;
            }
            ready = true;
            const theme = options.theme?.();
            options.frame()?.postMessage({ verb: 'init', nonce: options.nonce, role: options.role ?? 'panel', features: [...(options.features?.() ?? [])],
                ...(theme ? { theme } : {}) }, '*');
        },
    };
}
