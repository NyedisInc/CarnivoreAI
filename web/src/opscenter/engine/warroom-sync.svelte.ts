import { whenLegacyBootComplete } from '../../lib/legacy-boot';
import { warroomLayout } from './layout.svelte';
import { onWarroomChange } from './arrangement-events';
import { surfaceBusy } from './surface-busy';
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
let migrating = false;
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
  if (surfaceBusy()) {
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
  let migrated = false;
  applying = true;
  try {
    migrated = warroomLayout.adopt(next);
  } finally {
    applying = false;
  }
  if (migrated) {
    migrating = true;
    scheduleWrite();
  }
}

async function flush(): Promise<void> {
  const api = preferencesApi();
  if ((!dirty && !migrating) || !api) return;
  if (inflight || surfaceBusy() || api.status() !== api.HYDRATED) {
    scheduleWrite(RETRY_DELAY * 4);
    return;
  }
  const value = { v: 1, layout: live() };
  const userEdit = dirty;
  const migration = migrating;
  dirty = false;
  migrating = false;
  inflight = true;
  try {
    let result = await api.set(WARROOM_LAYOUT_FIELD, value);
    if (result.status === 'stale_revision') result = userEdit ? await api.set(WARROOM_LAYOUT_FIELD, value) : await resendMigration(api);
    if (result.status !== 'committed' && result.status !== 'unchanged') {
      dirty = dirty || userEdit;
      migrating = migrating || migration;
      scheduleWrite(RETRY_DELAY * 4);
    }
  } catch (error) {
    console.warn('[war room layout] write failed', error);
    dirty = dirty || userEdit;
    migrating = migrating || migration;
    scheduleWrite(RETRY_DELAY * 4);
  } finally {
    inflight = false;
  }
}

async function resendMigration(api: NonNullable<ReturnType<typeof preferencesApi>>): Promise<{ status: string }> {
  if (dirty) return { status: 'unchanged' };
  const theirs = parseWarroom(api.committedValue(WARROOM_LAYOUT_FIELD));
  if (!theirs) return { status: 'unchanged' };
  let migrated = false;
  applying = true;
  try {
    migrated = warroomLayout.adopt(theirs);
  } finally {
    applying = false;
  }
  return migrated ? api.set(WARROOM_LAYOUT_FIELD, { v: 1, layout: live() }) : { status: 'unchanged' };
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
  migrating = false;
  held = null;
  applying = false;
  inflight = false;
  if (writeTimer !== undefined) clearTimeout(writeTimer);
  if (heldTimer !== undefined) clearTimeout(heldTimer);
  writeTimer = undefined;
  heldTimer = undefined;
}
