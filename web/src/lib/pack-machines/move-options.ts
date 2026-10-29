/* not asleep */

export interface MoveOption {
  key: string;
  kind: 'company' | 'project';
  name: string;
}

export interface MoveGroups {
  active: MoveOption[];
  others: MoveOption[];
}

export interface MoveProject {
  id: number | null;
  name: string;
  company_id?: number | null;
}

export interface MoveSession {
  project_id?: number | null;
  activity_status?: string | null;
  asleep?: boolean;
}

const byName = (a: { name: string }, b: { name: string }): number =>
  a.name.toLowerCase().localeCompare(b.name.toLowerCase()) || a.name.localeCompare(b.name);

/* not asleep */
export function isLive(row: MoveSession): boolean {
  return row.asleep !== true && row.activity_status !== 'dead' && row.activity_status !== 'stopped';
}

export function moveGroups(companies: { id: number; name: string }[], projects: MoveProject[], sessions: MoveSession[]): MoveGroups {
  const liveProjects = new Set<number>();
  for (const row of sessions) if (row.project_id != null && isLive(row)) liveProjects.add(row.project_id);
  const liveCompanies = new Set<number>();
  for (const p of projects) if (p.id != null && p.company_id != null && liveProjects.has(p.id)) liveCompanies.add(p.company_id);
  const out: MoveGroups = { active: [], others: [] };
  const rows: (MoveOption & { live: boolean })[] = [
    ...[...companies].sort(byName).map((c) => ({ key: `c:${c.name}`, kind: 'company' as const, name: c.name, live: liveCompanies.has(c.id) })),
    ...[...projects].sort(byName).map((p) => ({ key: `p:${p.name}`, kind: 'project' as const, name: p.name, live: p.id != null && liveProjects.has(p.id) })),
  ];
  for (const { live, ...option } of rows) (live ? out.active : out.others).push(option);
  return out;
}
