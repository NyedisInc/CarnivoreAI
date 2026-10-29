import type { ProjectResponse, SessionInfo } from '../../opscenter/api/types';
import { t } from '../i18n/index.svelte';
import { type AgentMarkFacts } from '../sessions/agent-marks';

export interface MenuNode {
  id: string;
  label: string;
  children?: MenuNode[];
  run?: () => void;
  blocked?: string;
  sep?: boolean;
  checked?: boolean;
  agent?: AgentMarkFacts;
  aggregateLightHtml?: string;
  locked?: string;
  badge?: string;
  desc?: string;
  glyphHtml?: string;
  icon?: string;
  hint?: string;
  title?: string;
  keepOpen?: boolean;
  danger?: boolean;
  tone?: 'update';
  flash?: { run: () => Promise<boolean>; done: string };
  toggle?: boolean;
  swatches?: { value: string; allowNone?: boolean; onPick: (key: string) => void; onPreview?: (hex: string | null) => void };
}

export interface ProjectBucket {
  key: string;
  label: string;
  rows: SessionInfo[];
}

/* there is nothing */
export function bucketByProject(
  rows: readonly SessionInfo[],
  current: string,
  allProjects: readonly Pick<ProjectResponse, 'id' | 'name'>[] = [],
): ProjectBucket[] {
  const buckets = new Map<string, ProjectBucket>();
  for (const project of allProjects) {
    if (project.id === null || project.id === undefined) continue;
    const key = `p:${project.id}`;
    if (!buckets.has(key)) {
      buckets.set(key, { key, label: project.name || t('drawer.add.unnamed_project'), rows: [] });
    }
  }
  for (const row of rows) {
    if (current !== '' && row.session.id === current) continue;
    const pid = row.project_id;
    const known = pid !== null && pid !== undefined;
    const key = known ? `p:${pid}` : 'rogue';
    let bucket = buckets.get(key);
    if (!bucket) {
      const label = known ? (row.project_name || t('drawer.add.unnamed_project')) : t('drawer.add.rogue');
      bucket = { key, label, rows: [] };
      buckets.set(key, bucket);
    }
    bucket.rows.push(row);
  }
  const all = [...buckets.values()];
  return [...all.filter((b) => b.key !== 'rogue'), ...all.filter((b) => b.key === 'rogue')];
}

export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface Placement {
  left: number;
  top: number;
  maxHeight: number;
}

export const EDGE = 8;

export const OVERLAP = 8;

export function placeMenu(
  opener: Box,
  parent: Box | null,
  size: { width: number; height: number },
  view: { width: number; height: number },
): Placement {
  const maxLeft = Math.max(EDGE, view.width - size.width - EDGE);
  if (!parent) {
    const left = Math.max(EDGE, Math.min(opener.left, maxLeft));
    const top = opener.bottom + 4;
    const below = Math.max(0, view.height - top - EDGE);
    const above = Math.max(0, opener.top - 4 - EDGE);
    if (size.height > below && above > below) {
      return { left, top: Math.max(EDGE, opener.top - 4 - size.height), maxHeight: above };
    }
    return { left, top, maxHeight: below };
  }
  let left = parent.right - OVERLAP;
  if (left + size.width + EDGE > view.width) left = parent.left - size.width + OVERLAP;
  left = Math.max(EDGE, Math.min(left, maxLeft));
  const top = Math.max(EDGE, Math.min(opener.top - 4, view.height - size.height - EDGE));
  return { left, top, maxHeight: Math.max(0, view.height - top - EDGE) };
}

export function placeMenuAbove(
  opener: Box,
  size: { width: number; height: number },
  view: { width: number; height: number },
): Placement {
  const maxLeft = Math.max(EDGE, view.width - size.width - EDGE);
  const left = Math.max(EDGE, Math.min(opener.left, maxLeft));
  const room = Math.max(0, opener.top - 4 - EDGE);
  const top = Math.max(EDGE, opener.top - 4 - size.height);
  return { left, top, maxHeight: room };
}
