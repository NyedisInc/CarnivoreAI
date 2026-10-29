import { authFetch, familyOf, resourcePush } from '../sdk';
import { huddle, selectList } from './huddle.svelte';
import { AGGREGATE } from './huddle-model';
import { focusOpens } from './huddle-density';
import { taskManagerPrefs } from './task-manager-prefs.svelte';

export const FOCUS_FAMILY = 'cplug.huddle.focus';

export interface TaskManagerFocus {
  seq: number;
  list: string;
  items: number[];
  open: number | null;
}

export const taskManagerFocus = $state<{ focus: TaskManagerFocus | null; applied: number }>({ focus: null, applied: 0 });

export const revealWish = $state<{ id: number | null }>({ id: null });

export function isFocused(id: number): boolean {
  return taskManagerFocus.focus?.items.includes(id) ?? false;
}

export function focusCount(): number | null {
  const n = taskManagerFocus.focus?.items.length ?? 0;
  return n > 0 ? n : null;
}

let started = false;

export function startFocus(): void {
  if (started) return;
  started = true;
  resourcePush().onChange((topics) => {
    if (topics.some((topic) => familyOf(topic) === FOCUS_FAMILY)) void refreshFocus();
  });
  void refreshFocus();
}

function parse(body: unknown): TaskManagerFocus | null {
  const f = (body as { focus?: Partial<TaskManagerFocus> | null } | null)?.focus;
  if (!f || typeof f.seq !== 'number' || typeof f.list !== 'string' || !Array.isArray(f.items)) return null;
  const items = f.items.filter((i): i is number => typeof i === 'number');
  return { seq: f.seq, list: f.list, items, open: typeof f.open === 'number' ? f.open : null };
}

export async function applyFocus(focus: TaskManagerFocus | null): Promise<void> {
  taskManagerFocus.focus = focus;
  if (!focus || focus.seq === taskManagerFocus.applied) return;
  taskManagerFocus.applied = focus.seq;
  if (huddle.selected !== AGGREGATE && huddle.selected !== focus.list) await selectList(focus.list);
  const wished = focus.open !== null && revealWish.id === focus.open;
  if (wished) revealWish.id = null;
  if (focus.open !== null && (wished || focusOpens(taskManagerPrefs.density))) huddle.openId = focus.open;
}

export async function refreshFocus(): Promise<void> {
  try {
    await applyFocus(parse(await authFetch('/cplugs/huddle/focus')));
  } catch (error) {
    console.warn('huddle: could not read the focus', error);
  }
}

export async function clearFocus(): Promise<void> {
  if (!taskManagerFocus.focus) return;
  taskManagerFocus.focus = null;
  try {
    await authFetch('/cplugs/huddle/focus', { method: 'POST', body: JSON.stringify({ clear: true }) });
  } catch (error) {
    console.warn('huddle: could not clear the focus', error);
  }
}
