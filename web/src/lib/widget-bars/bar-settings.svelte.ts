import { whenLegacyBootComplete } from '../legacy-boot';
import { bridge } from '../zone-shell/preference-field';
import type { RailEdge } from '../session-rail/rail-model';
import { railStores } from '../session-rail/rail-store.svelte';

export type BarSize = 'compact' | 'cozy' | 'detailed';
export type BarMode = 'autohide' | 'pinned';
export type BarsTogether = 'both' | 'one';
export type PinEdge = RailEdge | 'rail';
export interface BarSettings {
  show: boolean;
  size: BarSize;
  mode: BarMode;
}
export interface WidgetBarsStored {
  v: 1;
  side?: Partial<BarSettings>;
  bottom?: Partial<BarSettings>;
  together?: BarsTogether;
  rail?: Partial<RailSettings>;
}
export interface RailSettings {
  mode: BarMode;
}
export interface WidgetBarsView {
  side: BarSettings;
  bottom: BarSettings;
  together: BarsTogether;
}
export type WriteResult = 'committed' | 'replayed' | 'unchanged' | 'conflict' | 'failed' | 'local_only';
export type BarPatch = { [K in keyof BarSettings]?: BarSettings[K] | null };

const FIELD = 'widget_bars';
const RESET_ROUTE = '/preferences/widget-bars/reset';

const SIZES: readonly BarSize[] = ['compact', 'cozy', 'detailed'];
const MODES: readonly BarMode[] = ['autohide', 'pinned'];
export const RAIL_DEFAULTS: Readonly<RailSettings> = Object.freeze({ mode: 'autohide' });

const EDGES: readonly RailEdge[] = ['side', 'bottom'];

export const BAR_DEFAULTS: Readonly<WidgetBarsView> = Object.freeze({
  side: Object.freeze({ show: true, size: 'cozy', mode: 'pinned' } as BarSettings),
  bottom: Object.freeze({ show: true, size: 'cozy', mode: 'pinned' } as BarSettings),
  together: 'both',
});

export function resolveBars(stored: WidgetBarsStored | null | undefined): WidgetBarsView {
  const side = { ...BAR_DEFAULTS.side, ...(stored?.side ?? {}) };
  const bottom = { ...BAR_DEFAULTS.bottom, ...(stored?.bottom ?? {}) };
  return { side, bottom, together: stored?.together ?? BAR_DEFAULTS.together };
}

function cleanBar(value: unknown): Partial<BarSettings> | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const raw = value as Record<string, unknown>;
  const out: Partial<BarSettings> = {};
  if (typeof raw.show === 'boolean') out.show = raw.show;
  if (SIZES.includes(raw.size as BarSize)) out.size = raw.size as BarSize;
  if (MODES.includes(raw.mode as BarMode)) out.mode = raw.mode as BarMode;
  return Object.keys(out).length ? out : undefined;
}

export function resolveRail(stored: WidgetBarsStored | null | undefined): RailSettings {
  return { ...RAIL_DEFAULTS, ...(stored?.rail ?? {}) };
}

function cleanRail(value: unknown): Partial<RailSettings> | undefined {
  const mode = value && typeof value === 'object' ? (value as Record<string, unknown>).mode : undefined;
  return MODES.includes(mode as BarMode) ? { mode: mode as BarMode } : undefined;
}

function normalize(value: unknown): WidgetBarsStored | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  if (raw.v !== 1) return null;
  const out: WidgetBarsStored = { v: 1 };
  const side = cleanBar(raw.side);
  const bottom = cleanBar(raw.bottom);
  if (side) out.side = side;
  if (bottom) out.bottom = bottom;
  if (raw.together === 'both' || raw.together === 'one') out.together = raw.together;
  const rail = cleanRail(raw.rail);
  if (rail) out.rail = rail;
  return out;
}

function sparse(next: WidgetBarsStored): WidgetBarsStored | null {
  return next.side || next.bottom || next.together || next.rail ? next : null;
}

function withPatch(stored: WidgetBarsStored | null, edge: RailEdge, patch: BarPatch): WidgetBarsStored | null {
  const next: WidgetBarsStored = { v: 1, ...(stored ?? {}) };
  const bar: Record<string, unknown> = { ...(next[edge] ?? {}) };
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) delete bar[key];
    else if (value !== undefined) bar[key] = value;
  }
  if (Object.keys(bar).length) next[edge] = bar as Partial<BarSettings>;
  else delete next[edge];
  return sparse(next);
}

function withTogether(stored: WidgetBarsStored | null, together: BarsTogether | null): WidgetBarsStored | null {
  const next: WidgetBarsStored = { v: 1, ...(stored ?? {}) };
  if (together === null) delete next.together;
  else next.together = together;
  return sparse(next);
}

function withRail(stored: WidgetBarsStored | null, mode: BarMode | null): WidgetBarsStored | null {
  const next: WidgetBarsStored = { v: 1, ...(stored ?? {}) };
  if (mode === null) delete next.rail;
  else next.rail = { mode };
  return sparse(next);
}

interface PreferencesLayer {
  committedValue?(name: string): unknown;
  discardLocal?(name: string): void;
  adopt?(body: unknown): void;
}
interface ApiLayer {
  call(route: string, options: { method: string }): Promise<unknown>;
}

function prefs(): PreferencesLayer | undefined {
  return (globalThis as { Preferences?: PreferencesLayer }).Preferences;
}

class WidgetBarsStore {
  #stored = $state<WidgetBarsStored | null>(null);
  #write = $state<'idle' | 'pending' | WriteResult>('idle');
  #started = false;

  get view(): WidgetBarsView {
    return resolveBars(this.#stored);
  }

  get rail(): RailSettings {
    return resolveRail(this.#stored);
  }

  get stored(): WidgetBarsStored | null {
    return this.#stored;
  }

  get customized(): boolean {
    return this.#stored !== null || railStores.side.stored !== null || railStores.bottom.stored !== null;
  }

  get write(): 'idle' | 'pending' | WriteResult {
    return this.#write;
  }

  isDefault(edge?: RailEdge): boolean {
    const edges = edge ? [edge] : EDGES;
    return edges.every((e) => this.#stored?.[e] === undefined && railStores[e].stored === null)
      && (edge !== undefined || this.#stored?.together === undefined);
  }

  start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
    if (this.#started) return;
    this.#started = true;
    this.reload();
    bridge()?.follow(FIELD, (value) => {
      this.#stored = normalize(value);
    });
    whenLegacyBootComplete(target, () => this.reload());
  }

  reload(): void {
    this.#stored = normalize(bridge()?.read(FIELD, () => null));
  }

  set(edge: RailEdge, patch: BarPatch): Promise<WriteResult> {
    return this.#commit((stored) => withPatch(stored, edge, patch));
  }

  setRail(mode: BarMode | null): Promise<WriteResult> {
    return this.#commit((stored) => withRail(stored, mode));
  }

  setTogether(together: BarsTogether | null): Promise<WriteResult> {
    return this.#commit((stored) => withTogether(stored, together));
  }

  async reset(): Promise<WriteResult> {
    this.#write = 'pending';
    const api = (globalThis as { API?: ApiLayer }).API;
    if (!api || typeof api.call !== 'function') return (this.#write = 'local_only');
    try {
      const body = (await api.call(RESET_ROUTE, { method: 'POST' })) as { status?: string } | null;
      prefs()?.adopt?.(body);
      this.reload();
      railStores.side.reload();
      railStores.bottom.reload();
      return (this.#write = body?.status === 'unchanged' ? 'unchanged' : 'committed');
    } catch (error) {
      console.warn('[widgetBars] reset failed', error);
      return (this.#write = 'failed');
    }
  }

  async #commit(op: (stored: WidgetBarsStored | null) => WidgetBarsStored | null): Promise<WriteResult> {
    const before = this.#stored;
    const next = op(before);
    if (JSON.stringify(next) === JSON.stringify(before)) return (this.#write = 'unchanged');
    this.#stored = next;
    this.#write = 'pending';
    const found = bridge();
    if (!found) return (this.#write = 'local_only');
    const first = await found.write(FIELD, next, () => {}) as { status?: string } | undefined;
    const status = first?.status;
    if (status === 'committed' || status === 'unchanged') return (this.#write = 'committed');
    if (status === 'local_only') return (this.#write = 'local_only');
    if (status !== 'stale_revision') {
      this.#stored = before;
      return (this.#write = 'failed');
    }
    const server = normalize(prefs()?.committedValue?.(FIELD));
    const replay = op(server);
    this.#stored = replay;
    const second = await found.write(FIELD, replay, () => {}) as { status?: string } | undefined;
    if (second?.status === 'committed' || second?.status === 'unchanged') return (this.#write = 'replayed');
    prefs()?.discardLocal?.(FIELD);
    this.#stored = normalize(prefs()?.committedValue?.(FIELD));
    return (this.#write = 'conflict');
  }
}

export const widgetBars = new WidgetBarsStore();
