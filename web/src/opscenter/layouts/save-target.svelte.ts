import { onLayoutArrangementChange } from '../engine/arrangement-events';
import { gestureActive } from '../engine/pointer';
import { groupsFor } from '../engine/tab-groups.svelte';
import { rekeyEntry } from '../engine/slot-identity';
import { terminalLayout } from '../engine/layout.svelte';
import { sessions } from '../api';
import type { Layout } from '../engine/types';
import { layoutError, putShape, type LayoutShape, type LayoutWrite, type SavedLayout } from './api';
import { toServerShape } from './shape';
import { layoutKeyOf, layoutMode } from './mode.svelte';

export const WRITE_DELAY = 600;

const RETRY_DELAY = 300;

export interface SaveHooks {
  landed(layout: SavedLayout): void;
  deleted(write: LayoutWrite): void;
  adopt(layout: SavedLayout): void;
  missing(): void;
  announce(line: string, kind: 'merged' | 'lost' | 'failed', reason?: string): void;
}

let hooks: SaveHooks | null = null;
let applying = false;
let dirty = false;
let inflight = false;
let timer: ReturnType<typeof setTimeout> | undefined;
let stop: (() => void) | null = null;
let lastShape = '';

export function currentShape(): LayoutShape | null {
  const key = terminalLayout.session;
  if (!layoutMode.uuid || key !== layoutKeyOf(layoutMode.uuid) || layoutMode.anchorRowId === null) return null;
  const layout = $state.snapshot(terminalLayout.state.layout) as Layout;
  const groups = $state.snapshot(groupsFor(key));
  const keyed = rekeyEntry({ layout, groups, active: {} }, sessions.data ?? [], false);
  return toServerShape(keyed.layout ?? layout, keyed.groups, layoutMode.anchorRowId);
}

export function noteSaved(shape: LayoutShape | null): void {
  lastShape = shape ? JSON.stringify(shape) : '';
}

export function whileApplying<T>(fn: () => T): T {
  applying = true;
  try {
    return fn();
  } finally {
    applying = false;
  }
}

function noteLocal(key: string): void {
  if (applying || !layoutMode.uuid || key !== layoutKeyOf(layoutMode.uuid)) return;
  dirty = true;
  schedule(WRITE_DELAY);
}

function schedule(delay: number): void {
  if (timer !== undefined) clearTimeout(timer);
  timer = setTimeout(() => {
    timer = undefined;
    void flushShape();
  }, delay);
}

export async function flushShape(): Promise<void> {
  if (!dirty || !layoutMode.uuid) return;
  if (inflight || gestureActive()) {
    schedule(RETRY_DELAY);
    return;
  }
  const shape = currentShape();
  if (!shape) return;
  dirty = false;
  const json = JSON.stringify(shape);
  if (json === lastShape) return;
  const uuid = layoutMode.uuid;
  inflight = true;
  try {
    await send(uuid, shape, json, true);
  } finally {
    inflight = false;
  }
  if (dirty) schedule(WRITE_DELAY);
}

async function send(uuid: string, shape: LayoutShape, json: string, replay: boolean): Promise<void> {
  let write: LayoutWrite;
  try {
    write = await putShape(uuid, shape, layoutMode.revision);
  } catch (error) {
    const refused = layoutError(error);
    if (uuid !== layoutMode.uuid) return;
    if (refused.code === 'layout_stale' && refused.current) {
      layoutMode.revision = refused.current.revision;
      if (replay) {
        await send(uuid, shape, json, false);
        if (lastShape === json) hooks?.announce('', 'merged');
        return;
      }
      noteSaved(refused.current.shape);
      hooks?.adopt(refused.current);
      hooks?.announce('', 'lost');
      return;
    }
    if (refused.status === 404) {
      hooks?.missing();
      return;
    }
    dirty = true;
    hooks?.announce('', 'failed', refused.detail);
    return;
  }
  if (uuid !== layoutMode.uuid) return;
  if (write.deleted) {
    hooks?.deleted(write);
    return;
  }
  if (write.layout) {
    layoutMode.revision = write.layout.revision;
    layoutMode.members = write.layout.members;
    lastShape = json;
    hooks?.landed(write.layout);
  }
}

export function startSaveTarget(next: SaveHooks): void {
  hooks = next;
  if (!stop) stop = onLayoutArrangementChange(noteLocal);
}

export function savePending(): boolean {
  return dirty || inflight;
}

export function dropPending(): void {
  dirty = false;
  lastShape = '';
  if (timer !== undefined) clearTimeout(timer);
  timer = undefined;
}

export function resetSaveTarget(): void {
  stop?.();
  stop = null;
  hooks = null;
  applying = false;
  inflight = false;
  dropPending();
}
