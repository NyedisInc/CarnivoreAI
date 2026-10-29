import type { ProjectChoice, SessionChoice } from './api';
import type { TaskManagerSchedule } from '../task-manager-schedules/task-manager-scheduled';

export const UNASSIGNED_KEY = 'unassigned';

export interface SchedNode {
  key: string;
  kind: 'project' | 'session' | 'unassigned';
  label: string;
  schedules: TaskManagerSchedule[];
  children: SchedNode[];
}

const byName = (a: { label: string }, b: { label: string }): number => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' });

function bySoonest(a: TaskManagerSchedule, b: TaskManagerSchedule): number {
  const at = (s: TaskManagerSchedule): number => (s.paused || s.fireAt === null ? Number.POSITIVE_INFINITY : s.fireAt);
  return at(a) - at(b) || a.title.localeCompare(b.title);
}

function node(kind: SchedNode['kind'], key: string, label: string): SchedNode {
  return { key, kind, label, schedules: [], children: [] };
}

export function buildScheduledTree(projects: readonly ProjectChoice[], sessions: readonly SessionChoice[], schedules: readonly TaskManagerSchedule[]): SchedNode[] {
  const projectNodes = new Map<number, SchedNode>();
  for (const p of projects) if (p.id !== null) projectNodes.set(p.id, node('project', `project:${p.id}`, p.name));
  const unassigned = node('unassigned', UNASSIGNED_KEY, '');
  const sessionNodes = new Map<string, SchedNode>();
  for (const s of sessions) {
    if (!s.session_uuid || s.archived_at) continue;
    const home = (s.project_id ?? null) !== null ? projectNodes.get(s.project_id as number) : undefined;
    const leaf = node('session', `session:${s.session_uuid}`, s.label ?? s.tmux_name ?? s.name ?? '');
    sessionNodes.set(s.session_uuid, leaf);
    (home ?? unassigned).children.push(leaf);
  }
  for (const item of schedules) {
    const projectId = item.projectId ?? null;
    (sessionNodes.get(item.sessionKey ?? '') ?? (projectId !== null ? projectNodes.get(projectId) : undefined) ?? unassigned).schedules.push(item);
  }
  const keep = (n: SchedNode): SchedNode | null => {
    const children = n.children.map(keep).filter((c): c is SchedNode => c !== null).sort(byName);
    if (n.schedules.length === 0 && children.length === 0) return null;
    return { ...n, schedules: [...n.schedules].sort(bySoonest), children };
  };
  const top = [...projectNodes.values()].sort(byName);
  top.push(unassigned);
  return top.map(keep).filter((n): n is SchedNode => n !== null);
}
