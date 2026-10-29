import { whenLegacyBootComplete } from '../../lib/legacy-boot';
import { warroomLayout } from './layout.svelte';
import { onWarroomChange } from './arrangement-events';
import { gestureActive } from './pointer';
import { preferencesApi } from './arrangement-sync.svelte';
import type { Layout } from './types';

export const WARROOM_LAYOUT_FIELD = 'warroom_layout';

export const WRITE_DELAY = 600;

const RETRY_DELAY = 300;

export function parseWarroom(value: unknown): Layout | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const layout = (value as Record<string, unknown>)['layout'];
  return layout && typeof layout === 'object' && !Array.isArray(layout) ? (layout as Layout) : null;
}

let dirty = false;
let applying = false;
let inflight = false;
let started = false;
let held: Layout | null = null;
let writeTimer: ReturnType<typeof setTimeout> | undefined;
let heldTimer: ReturnType<typeof setTimeout> | undefined;
let stops: Array<() => void> = [];

function live(): Layout {
  return $state.snapshot(warroomLayout.state.layout) as Layout;
}

function scheduleWrite(delay = WRITE_DELAY): void {
  if (writeTimer !== undefined) clearTimeout(writeTimer);
  writeTimer = setTimeout(() => {
    writeTimer = undefined;
    void flush();
  }, delay);
}

function noteLocal(): void {
  if (applying) return;
  dirty = true;
  scheduleWrite();
}

export function applyWarroom(next: Layout): void {
  if (gestureActive()) {
    held = next;
    if (heldTimer === undefined) {
      heldTimer = setTimeout(() => {
        heldTimer = undefined;
        const value = held;
        held = null;
        if (value) applyWarroom(value);
      }, RETRY_DELAY);
    }
    return;
  }
  held = null;
  if (dirty) return;
  if (JSON.stringify(live()) === JSON.stringify(next)) return;
  applying = true;
  try {
    warroomLayout.adopt(next);
  } finally {
    applying = false;
  }
}

async function flush(): Promise<void> {
  const api = preferencesApi();
  if (!dirty || !api) return;
  if (inflight || gestureActive() || api.status() !== api.HYDRATED) {
    scheduleWrite(RETRY_DELAY * 4);
    return;
  }
  const value = { v: 1, layout: live() };
  dirty = false;
  inflight = true;
  try {
    let result = await api.set(WARROOM_LAYOUT_FIELD, value);
    if (result.status === 'stale_revision') result = await api.set(WARROOM_LAYOUT_FIELD, value);
    if (result.status !== 'committed' && result.status !== 'unchanged') {
      dirty = true;
      scheduleWrite(RETRY_DELAY * 4);
    }
  } catch (error) {
    console.warn('[war room layout] write failed', error);
    dirty = true;
    scheduleWrite(RETRY_DELAY * 4);
  } finally {
    inflight = false;
  }
}

export function hydrateWarroom(): void {
  const api = preferencesApi();
  if (!api || api.status() !== api.HYDRATED || inflight) return;
  const value = parseWarroom(api.committedValue(WARROOM_LAYOUT_FIELD));
  if (value) applyWarroom(value);
}

export function startWarroomSync(target: Window | null = typeof window !== 'undefined' ? window : null): void {
  if (started) return;
  started = true;
  stops.push(onWarroomChange(noteLocal));
  const api = preferencesApi();
  if (api) {
    stops.push(
      api.subscribe((name, value, record) => {
        if (name !== WARROOM_LAYOUT_FIELD || record?.state !== api.COMMITTED || inflight) return;
        const next = parseWarroom(value);
        if (next) applyWarroom(next);
      }),
    );
  }
  whenLegacyBootComplete(target, hydrateWarroom);
  const onVisible = (): void => {
    if (target?.document?.visibilityState === 'visible') hydrateWarroom();
  };
  target?.document?.addEventListener('visibilitychange', onVisible);
  stops.push(() => target?.document?.removeEventListener('visibilitychange', onVisible));
}

export function resetWarroomSync(): void {
  for (const stop of stops) stop();
  stops = [];
  started = false;
  dirty = false;
  held = null;
  applying = false;
  inflight = false;
  if (writeTimer !== undefined) clearTimeout(writeTimer);
  if (heldTimer !== undefined) clearTimeout(heldTimer);
  writeTimer = undefined;
  heldTimer = undefined;
}
