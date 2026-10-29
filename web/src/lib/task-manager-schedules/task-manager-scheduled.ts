import { ALL_LIST, TASK_MANAGER_FAMILY, type HuddleItem, type TaskManagerRepeat } from '../../cplugs/huddle/huddle-model';
import { authFetch } from '../../opscenter/api/auth.svelte';

export const TASK_MANAGER_SCHEDULED_ROUTE = '/cplugs/huddle/scheduled';

export interface TaskManagerSchedule {
  list: string;
  item: number;
  title: string;
  fireAt: number | null;
  paused: boolean;
  state: string;
  sessionKey: string | null;
  project?: string | null;
  projectId?: number | null;
  repeat?: TaskManagerRepeat | null;
  source?: HuddleItem | null;
}

interface ScheduledWire {
  list: string;
  item: number;
  title: string;
  next_fire: string | null;
  paused: boolean;
  state: string;
  repeat?: TaskManagerRepeat | null;
  pings?: { session_key?: string | null; project?: string | null; project_id?: number | null };
}

export interface ScheduledViewBody {
  schedules?: ScheduledWire[];
  groups?: { items: HuddleItem[] }[];
}

export function taskManagerSchedules(body: ScheduledViewBody | null): TaskManagerSchedule[] {
  const items = new Map<number, HuddleItem>();
  for (const group of body?.groups ?? []) for (const item of group.items) items.set(item.id, item);
  const out: TaskManagerSchedule[] = [];
  for (const s of body?.schedules ?? []) {
    if (s.state === 'fired') continue;
    const at = s.next_fire ? Date.parse(s.next_fire) / 1000 : NaN;
    out.push({ list: s.list, item: s.item, title: s.title, fireAt: Number.isFinite(at) ? at : null, paused: s.paused, state: s.state, sessionKey: s.pings?.session_key ?? null, project: s.pings?.project ?? null,
      projectId: s.pings?.project_id ?? null, repeat: s.repeat ?? null, source: items.get(s.item) ?? null });
  }
  return out;
}

export const TASK_MANAGER_TOPICS = [`${TASK_MANAGER_FAMILY}:${ALL_LIST}`];

/* a network failure */
export async function readTaskManagerSchedules(): Promise<TaskManagerSchedule[]> {
  return taskManagerSchedules(await authFetch<ScheduledViewBody>(TASK_MANAGER_SCHEDULED_ROUTE));
}
