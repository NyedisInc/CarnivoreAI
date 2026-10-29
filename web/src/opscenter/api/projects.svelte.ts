
import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import type { ProjectResponse } from './types';
import { projects as demoProjects } from '../data/projects';

export const PROJECTS_POLL_MS = 15000;

function demoList(): ProjectResponse[] {
  const now = Date.now();
  return demoProjects.map((row, index) => ({
    id: index + 1,
    name: row.name,
    path: row.path,
    description: null,
    root: row.path,
    work_at: new Date(now - row.updatedMinutes * 60_000).toISOString(),
    archived_at: null,
  }));
}

export const projects: Resource<ProjectResponse[]> = resource<ProjectResponse[]>(
  () => authFetch<ProjectResponse[]>('/projects'),
  { intervalMs: PROJECTS_POLL_MS, name: 'projects', demo: demoList, topics: ['projects'] },
);
