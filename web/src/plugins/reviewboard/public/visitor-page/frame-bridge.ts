
const VERSION = 1;
const MAX_MESSAGE = 4096;
const MAX_PAYLOAD_MESSAGE = 64 * 1024 + 1024;
const MAX_PER_SECOND = 20;
const MAX_DEPTH = 32;
export const ECHO_MS = 600;

export interface VisitorFrameHandlers {
  ready(): void;
  payload(payload: Record<string, unknown>): void;
}

export type FrameMessage = Pick<MessageEvent, 'source' | 'origin' | 'data'>;

export interface VisitorBridge {
  handle(event: FrameMessage): boolean;
  theme(vars: Record<string, string>): void;
  strings(map: Record<string, string>): void;
  load(payload: Record<string, unknown>): void;
  mode(readonly: boolean): void;
}

function plain(value: unknown, depth = 0): boolean {
  if (depth > MAX_DEPTH) return false;
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every((item) => plain(item, depth + 1));
  if (typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) return Object.values(value).every((item) => plain(item, depth + 1));
  return false;
}

function size(data: unknown): number {
  try {
    return JSON.stringify(data)?.length ?? Number.POSITIVE_INFINITY;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

export function createVisitorBridge(frame: () => HTMLIFrameElement | null, handlers: VisitorFrameHandlers, now: () => number = Date.now): VisitorBridge {
  let windowStart = 0;
  let inWindow = 0;
  let quietUntil = Number.POSITIVE_INFINITY;

  const post = (type: string, fields: Record<string, unknown>): void => {
    const message = JSON.parse(JSON.stringify({ rb: VERSION, type, ...fields })) as Record<string, unknown>;
    frame()?.contentWindow?.postMessage(message, '*');
  };

  return {
    handle(event) {
      const target = frame()?.contentWindow;
      if (!target || event.source !== target || event.origin !== 'null') return false;
      const t = now();
      if (t - windowStart >= 1000) { windowStart = t; inWindow = 0; }
      inWindow += 1;
      if (inWindow > MAX_PER_SECOND) return false;
      const data = event.data as { rb?: unknown; type?: unknown; payload?: unknown } | null;
      if (!data || typeof data !== 'object' || data.rb !== VERSION) return false;
      if (size(data) > (data.type === 'payload' ? MAX_PAYLOAD_MESSAGE : MAX_MESSAGE)) return false;
      if (data.type === 'ready') {
        quietUntil = t + ECHO_MS;
        handlers.ready();
        return true;
      }
      if (data.type !== 'payload' || !plain(data.payload) || typeof data.payload !== 'object' || data.payload === null || Array.isArray(data.payload)) return false;
      if (t < quietUntil) return false;
      handlers.payload(data.payload as Record<string, unknown>);
      return true;
    },
    theme: (vars) => post('theme', { id: 'owner', vars }),
    strings: (map) => post('strings', { map }),
    mode: (readonly) => post('mode', { readonly }),
    load: (payload) => {
      quietUntil = now() + ECHO_MS;
      post('load', { payload, save: null });
    },
  };
}

export function wearTheme(root: HTMLElement, vars: Record<string, string> | null | undefined): void {
  for (const [name, value] of Object.entries(vars ?? {})) if (name.startsWith('--oc-')) root.style.setProperty(name, value);
}
