import { authFetch, familyOf, resourcePush } from '../sdk';
import type { ProgressLine } from './huddle-progress';

export const PROGRESS_FAMILY = 'cplug.huddle.progress';

const TICK_MS = 15_000;

export const taskManagerProgress = $state<{ byItem: Record<string, ProgressLine[]>; readAt: number; now: number }>({
  byItem: {}, readAt: Date.now(), now: Date.now(),
});

let started = false;
let timer: ReturnType<typeof setInterval> | null = null;

export function progressOf(id: number): ProgressLine[] {
  return taskManagerProgress.byItem[String(id)] ?? [];
}

export function sinceRead(): number {
  return Math.max(0, taskManagerProgress.now - taskManagerProgress.readAt);
}

export function parse(body: unknown): Record<string, ProgressLine[]> {
  const raw = (body as { progress?: Record<string, unknown> } | null)?.progress;
  const out: Record<string, ProgressLine[]> = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const [id, lines] of Object.entries(raw)) {
    if (!Array.isArray(lines)) continue;
    const ok = lines.filter((l): l is ProgressLine => !!l && typeof l.worker === 'string' && typeof l.phase === 'string'
      && typeof l.age_s === 'number');
    if (ok.length) out[id] = ok.map((l) => ({ ...l, note: typeof l.note === 'string' ? l.note : '', stale: l.stale === true }));
  }
  return out;
}

function syncTick(): void {
  const live = Object.keys(taskManagerProgress.byItem).length > 0;
  if (live && timer === null) timer = setInterval(() => { taskManagerProgress.now = Date.now(); }, TICK_MS);
  if (!live && timer !== null) { clearInterval(timer); timer = null; }
}

export function applyProgress(body: unknown): void {
  taskManagerProgress.byItem = parse(body);
  taskManagerProgress.readAt = taskManagerProgress.now = Date.now();
  syncTick();
}

export async function refreshProgress(): Promise<void> {
  try {
    applyProgress(await authFetch('/cplugs/huddle/progress'));
  } catch (error) {
    console.warn('huddle: could not read worker progress', error);
  }
}

export function startProgress(): void {
  if (started) return;
  started = true;
  resourcePush().onChange((topics) => {
    if (topics.some((topic) => familyOf(topic) === PROGRESS_FAMILY)) void refreshProgress();
  });
  void refreshProgress();
}
