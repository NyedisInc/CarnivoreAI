import type { ProjectResponse, SessionInfo } from '../../api';

export function countForProject(rows: readonly SessionInfo[], project: ProjectResponse): number | null {
  if (project.id === null) return null;
  return rows.filter((row) => row.project_id === project.id).length;
}
