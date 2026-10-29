import { projects } from '../../opscenter/api/projects.svelte';
import { isProjectColor, type ProjectColor } from './palette';

export function projectColorOf(projectId: number | null): ProjectColor | null {
  if (projectId === null) return null;
  const color = projects.data?.find((row) => row.id === projectId)?.color;
  return isProjectColor(color) ? color : null;
}
