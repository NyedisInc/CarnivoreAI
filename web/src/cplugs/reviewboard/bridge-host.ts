import { MAX_PAYLOAD_BYTES, validatePayload, type Payload } from './payload-model';

export const BRIDGE_VERSION = 1;
export const MAX_MESSAGE_BYTES = 4096;
export const MAX_PER_SECOND = 20;
export const MAX_PAYLOAD_MESSAGE_BYTES = MAX_PAYLOAD_BYTES + 1024;
export const FRAME_TYPES: readonly string[] = ['ready', 'anchor', 'payload', 'layout'];
export const MAX_GAP_PX = 1200;
const MAX_COORDINATE = 100000;
const MAX_ANCHORS = 60;

export type DropReason = 'source' | 'origin' | 'size' | 'shape' | 'type' | 'rate' | 'undeclared' | 'payload';

export interface GapSpot { x: number; y: number; w: number }
export type GapLayout = Record<string, GapSpot>;

export function gapSpots(value: unknown, declared: ReadonlySet<string>): GapLayout | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const out: GapLayout = {};
  for (const [id, raw] of Object.entries(value as Record<string, unknown>).slice(0, MAX_ANCHORS)) {
    if (!declared.has(id) || !Array.isArray(raw) || raw.length !== 3) continue;
    const [x, y, w] = raw;
    if ([x, y, w].every((n) => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= MAX_COORDINATE)) out[id] = { x: x as number, y: y as number, w: Math.max(0, w as number) };
  }
  return out;
}

export interface BridgeHandlers {
  ready(info: { anchors: string[]; themeAware: boolean }): void;
  anchor(id: string): void;
  payload?(payload: Payload): void;
  layout?(spots: GapLayout): void;
  dropped?(reason: DropReason, count: number): void;
}

export type FrameEvent = Pick<MessageEvent, 'source' | 'origin' | 'data'>;

export interface BridgeOptions {
  frame: () => HTMLIFrameElement | null;
  declared: () => Iterable<string>;
  handlers: BridgeHandlers;
  now?: () => number;
}

export interface BridgeHost {
  handle(event: FrameEvent): boolean;
  highlight(anchor: string): void;
  state(answered: string[], noted: string[]): void;
  gaps(rooms: Record<string, number>): void;
  load(payload: Payload, save: number | null): void;
  strings(map: Record<string, string>): void;
  theme(id: string, vars: Record<string, string>): void;
}

export function createBridgeHost(options: BridgeOptions): BridgeHost {
  const now = options.now ?? (() => Date.now());
  let windowStart = 0;
  let inWindow = 0;
  let droppedInWindow = 0;
  let reportedRate = false;

  function drop(reason: DropReason): false {
    droppedInWindow += 1;
    if (reason !== 'rate' || !reportedRate) options.handlers.dropped?.(reason, droppedInWindow);
    if (reason === 'rate') reportedRate = true;
    return false;
  }

  function withinRate(): boolean {
    const t = now();
    if (t - windowStart >= 1000) {
      windowStart = t;
      inWindow = 0;
      droppedInWindow = 0;
      reportedRate = false;
    }
    inWindow += 1;
    return inWindow <= MAX_PER_SECOND;
  }

  function bodySize(data: unknown): number {
    try {
      return JSON.stringify(data)?.length ?? Number.POSITIVE_INFINITY;
    } catch {
      return Number.POSITIVE_INFINITY;
    }
  }

  function post(type: string, fields: Record<string, unknown>): void {
    options.frame()?.contentWindow?.postMessage({ rb: BRIDGE_VERSION, type, ...fields }, '*');
  }

  return {
    handle(event) {
      const frame = options.frame();
      if (!frame || !frame.contentWindow || event.source !== frame.contentWindow) return drop('source');
      if (event.origin !== 'null') return drop('origin');
      if (!withinRate()) return drop('rate');
      const data = event.data as { rb?: unknown; type?: unknown; anchor?: unknown; anchors?: unknown; theme_aware?: unknown; payload?: unknown } | null;
      const limit = data && typeof data === 'object' && data.type === 'payload' ? MAX_PAYLOAD_MESSAGE_BYTES : MAX_MESSAGE_BYTES;
      if (bodySize(event.data) > limit) return drop('size');
      if (!data || typeof data !== 'object' || data.rb !== BRIDGE_VERSION || typeof data.type !== 'string') return drop('shape');
      if (!FRAME_TYPES.includes(data.type)) return drop('type');
      if (data.type === 'payload') {
        const plain = validatePayload(data.payload);
        if (plain === null) return drop('payload');
        options.handlers.payload?.(plain);
        return true;
      }
      const declared = new Set(options.declared());
      if (data.type === 'layout') {
        const spots = gapSpots((data as { gaps?: unknown }).gaps, declared);
        if (spots === null) return drop('shape');
        options.handlers.layout?.(spots);
        return true;
      }
      if (data.type === 'anchor') {
        if (typeof data.anchor !== 'string' || !declared.has(data.anchor)) return drop('undeclared');
        options.handlers.anchor(data.anchor);
        return true;
      }
      const named = Array.isArray(data.anchors) ? data.anchors.filter((a): a is string => typeof a === 'string').slice(0, MAX_ANCHORS) : [];
      options.handlers.ready({ anchors: named.filter((a) => declared.has(a)), themeAware: data.theme_aware === true });
      return true;
    },
    highlight: (anchor) => post('highlight', { anchor }),
    gaps: (rooms) => {
      const clean: Record<string, number> = {};
      for (const [id, px] of Object.entries(rooms).slice(0, MAX_ANCHORS)) if (Number.isFinite(px)) clean[id] = Math.min(MAX_GAP_PX, Math.max(0, Math.round(px)));
      post('gaps', { gaps: clean });
    },
    state: (answered, noted) => post('state', { answered_anchors: answered, noted_anchors: noted }),
    load: (payload, save) => post('load', { payload: JSON.parse(JSON.stringify(payload)) as Payload, save }),
    strings: (map) => post('strings', { map }),
    theme: (id, vars) => post('theme', { id, vars }),
  };
}
