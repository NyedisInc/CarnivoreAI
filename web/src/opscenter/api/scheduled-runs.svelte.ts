/* did not answer */
import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import { resourcePush } from '../../lib/resource-push/boot';
import { listProjectChoices, type Automation } from '../../lib/automations/api';
import { TASK_MANAGER_TOPICS, readTaskManagerSchedules, type TaskManagerSchedule } from '../../lib/task-manager-schedules/task-manager-scheduled';
import type { RunRow } from '../cells/developer/model';

export const SCHEDULED_RUNS_POLL_MS = 15000;
export const SCHEDULED_RUNS_TOPICS: readonly string[] = ['automations', 'automation_runs'];
export const PROJECT_NAMES_TOPIC = 'projects';
export const RUNS_READ = 40;

export interface ScheduledRuns {
  automations: Automation[];
  runs: RunRow[];
  projects: Record<number, string>;
}

let projectNames: Record<number, string> | null = null;
/* did not answer new read */
const unanswered = new Set<number>();

function forgetProjectNames(): void {
  projectNames = null;
  unanswered.clear();
}

async function namesFor(automations: readonly Automation[]): Promise<Record<number, string>> {
  const wanted = automations.map((a) => a.project_id).filter((id): id is number => typeof id === 'number');
  if (wanted.length === 0) return projectNames ?? {};
  const known = projectNames;
  if (known && wanted.every((id) => id in known || unanswered.has(id))) return known;
  try {
    const names: Record<number, string> = {};
    for (const p of await listProjectChoices()) if (p.id !== null) names[p.id] = p.name;
    projectNames = names;
    for (const id of wanted) if (!(id in names)) unanswered.add(id);
  } catch (error) {
    console.warn('scheduled_runs_projects_unread', error);
  }
  return projectNames ?? {};
}

export async function readScheduledRuns(): Promise<ScheduledRuns> {
  const [autos, runs] = await Promise.all([
    authFetch<{ automations: Automation[] }>('/automations'),
    authFetch<{ runs: RunRow[] }>(`/automations/runs?limit=${RUNS_READ}`),
  ]);
  const automations = autos?.automations ?? [];
  return { automations, runs: runs?.runs ?? [], projects: await namesFor(automations) };
}

let current: Resource<ScheduledRuns> | null = null;
let refs = 0;
let offProjects: (() => void) | null = null;

export function acquireScheduledRuns(): Resource<ScheduledRuns> {
  if (current === null) {
    current = resource<ScheduledRuns>(readScheduledRuns, {
      intervalMs: SCHEDULED_RUNS_POLL_MS,
      topics: [...SCHEDULED_RUNS_TOPICS],
      name: 'scheduled-runs',
      demo: () => ({ automations: [], runs: [], projects: {} }),
    });
    offProjects = resourcePush().onChange((names) => {
      if (!names.includes(PROJECT_NAMES_TOPIC) || current === null) return;
      forgetProjectNames();
      void current.refresh(true);
    });
  }
  refs += 1;
  return current;
}

export function releaseScheduledRuns(): void {
  if (current === null) return;
  refs -= 1;
  if (refs <= 0) {
    current.stop();
    current = null;
    refs = 0;
    offProjects?.();
    offProjects = null;
    forgetProjectNames();
  }
}

let taskManagerRead: Resource<TaskManagerSchedule[]> | null = null;
let taskManagerRefs = 0;

export function acquireTaskManagerSchedules(): Resource<TaskManagerSchedule[]> {
  if (taskManagerRead === null) {
    taskManagerRead = resource<TaskManagerSchedule[]>(readTaskManagerSchedules, {
      intervalMs: SCHEDULED_RUNS_POLL_MS,
      topics: [...TASK_MANAGER_TOPICS],
      name: 'scheduled-huddle',
      demo: () => [],
    });
  }
  taskManagerRefs += 1;
  return taskManagerRead;
}

export function releaseTaskManagerSchedules(): void {
  if (taskManagerRead === null) return;
  taskManagerRefs -= 1;
  if (taskManagerRefs <= 0) {
    taskManagerRead.stop();
    taskManagerRead = null;
    taskManagerRefs = 0;
  }
}
