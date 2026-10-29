import { authFetch } from '../sdk';
import { isAgentList, type TaskManagerSession } from './huddle-model';

export const START_NEW = 'start:new';
export const STOP = 'start:stop';

export const READY_TIMEOUT_MS = 90_000;
export const READY_STEP_MS = 1_500;

interface ProjectRow {
  id: number;
  name: string;
  path: string;
  default_launch_profile?: string | null;
}

export type StartFailure = 'no_project' | 'create_failed' | 'not_ready';

export interface StartResult {
  session: string | null;
  failure: StartFailure | null;
}

export function createPayload(project: ProjectRow): Record<string, unknown> {
  const body: Record<string, unknown> = {
    working_dir: project.path, auto_start_claude: true, copy_templates: false, project_name: project.name, label: project.name,
  };
  if (project.default_launch_profile) body.agent_type = project.default_launch_profile;
  return body;
}

export async function startSessionFor(list: string): Promise<StartResult> {
  if (isAgentList(list)) return { session: null, failure: 'no_project' };
  let projects: ProjectRow[];
  try {
    projects = (await authFetch<ProjectRow[] | null>('/projects')) ?? [];
  } catch (error) {
    console.warn('huddle: could not read the projects to start a session', error);
    return { session: null, failure: 'no_project' };
  }
  const project = projects.find((p) => String(p.id) === list);
  if (!project) return { session: null, failure: 'no_project' };
  try {
    const created = await authFetch<{ id?: string } | null>('/sessions', { method: 'POST', body: JSON.stringify(createPayload(project)) });
    return created?.id ? { session: created.id, failure: null } : { session: null, failure: 'create_failed' };
  } catch (error) {
    console.warn('huddle: could not start a session for list', list, error);
    return { session: null, failure: 'create_failed' };
  }
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

export async function waitUntilReady(list: string, session: string, timeoutMs = READY_TIMEOUT_MS, stepMs = READY_STEP_MS): Promise<boolean> {
  const until = Date.now() + timeoutMs;
  for (;;) {
    try {
      const found = await authFetch<{ sessions?: TaskManagerSession[] } | null>(`/cplugs/huddle/lists/${encodeURIComponent(list)}/sessions`);
      if ((found?.sessions ?? []).some((s) => s.id === session && s.activity_status === 'idle')) return true;
    } catch (error) {
      console.warn('huddle: could not read the new session yet', error);
    }
    if (Date.now() + stepMs > until) return false;
    await sleep(stepMs);
  }
}
