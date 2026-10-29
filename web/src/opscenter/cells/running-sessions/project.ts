
import type { ProjectResponse } from '../../api';
import { t } from '../../../lib/i18n/index.svelte';

export function leaf(path: string): string {
  const trimmed = path.replace(/\/+$/, '');
  const at = trimmed.lastIndexOf('/');
  return at >= 0 ? trimmed.slice(at + 1) : trimmed;
}

export function projectFor(workingDir: string, projectRows: readonly ProjectResponse[]): string {
  const dirLeaf = leaf(workingDir);
  if (!dirLeaf) return t('opscenter.value.unknown');
  for (const project of projectRows) {
    const identity = project.root ?? project.path;
    if (identity && leaf(identity) === dirLeaf) return project.name;
  }
  return dirLeaf;
}

export function majorityProject(workingDirs: readonly string[], projectRows: readonly ProjectResponse[]): string {
  const counts = new Map<string, number>();
  for (const dir of workingDirs) {
    const key = projectFor(dir, projectRows);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  let best = '';
  let bestCount = -1;
  for (const [key, count] of counts) {
    if (count > bestCount) {
      best = key;
      bestCount = count;
    }
  }
  return best;
}
