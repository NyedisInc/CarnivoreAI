import type { TaskItem } from '../sdk';
import type { TaskManagerDeltaItem, TaskManagerDeltaWire } from '../sdk/task-manager-delta';

export interface StepsEntry {
  tasks: TaskItem[];
  counts: { pending: number; in_progress: number; completed: number };
}

export interface ListSteps {
  items: Record<string, StepsEntry>;
}

export interface StepsSummary {
  done: number;
  total: number;
  now: string | null;
}

export function summarize(entry: StepsEntry): StepsSummary {
  const running = entry.tasks.find((task) => task.status === 'in_progress');
  const { pending, in_progress, completed } = entry.counts;
  return { done: completed, total: pending + in_progress + completed, now: running ? (running.active_form || running.subject) : null };
}

export function hasOpenSteps(entry: StepsEntry | null | undefined): entry is StepsEntry {
  return !!entry && entry.counts.pending + entry.counts.in_progress > 0;
}

export function parseSteps(body: unknown): Record<string, ListSteps> {
  const raw = (body as { lists?: Record<string, unknown> } | null)?.lists;
  const out: Record<string, ListSteps> = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const [list, value] of Object.entries(raw)) {
    const v = value as { items?: Record<string, StepsEntry> } | null;
    const items: Record<string, StepsEntry> = {};
    for (const [id, entry] of Object.entries(v?.items ?? {})) if (hasOpenSteps(entry)) items[id] = entry;
    if (Object.keys(items).length) out[list] = { items };
  }
  return out;
}

export type ClaimKey = string | null;

const OWNER_UNKNOWN = '?';

export function claimKeyOf(item: TaskManagerDeltaItem): ClaimKey {
  return item.status === 'working' ? `${item.list}|${item.owner_session_key ?? ''}` : null;
}

function shownList(byList: Record<string, ListSteps>, id: number): string | null {
  for (const [list, steps] of Object.entries(byList)) if (steps.items[String(id)]) return list;
  return null;
}

function sameClaim(before: ClaimKey, after: ClaimKey): boolean {
  if (before === null || after === null) return before === after;
  const [beforeList, beforeOwner] = before.split('|');
  const [afterList, afterOwner] = after.split('|');
  return beforeList === afterList && (beforeOwner === OWNER_UNKNOWN || beforeOwner === afterOwner);
}

export function stepsMoved(byList: Record<string, ListSteps>, delta: TaskManagerDeltaWire, claims: Map<number, ClaimKey>): boolean {
  let moved = false;
  for (const entry of delta.lists ?? []) {
    for (const id of entry.deleted) {
      if (claims.get(id) || shownList(byList, id) !== null) moved = true;
      claims.delete(id);
    }
    for (const item of entry.items) {
      const shown = shownList(byList, item.id);
      const before: ClaimKey = claims.has(item.id) ? (claims.get(item.id) ?? null) : shown !== null ? `${shown}|${OWNER_UNKNOWN}` : null;
      const after = claimKeyOf(item);
      if (!sameClaim(before, after)) moved = true;
      claims.set(item.id, after);
    }
  }
  return moved;
}
