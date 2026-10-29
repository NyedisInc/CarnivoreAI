import type { SessionGitStatus } from '../../api/types';

export const CHIP_SYNC_MIN = 360;
export const CHIP_REPO_MIN = 300;
export const CHIP_DOT_MIN = 240;

export interface ChipParts {
  kind: 'unknown' | 'branch';
  repo: string;
  branch: string;
  detached: boolean;
  unborn: boolean;
  dirty: boolean;
  sync: string;
}

export function chipParts(status: SessionGitStatus | null, width: number, unreadable = false): ChipParts | null {
  const roomy = (min: number): boolean => width <= 0 || width >= min;
  const base = { repo: '', detached: false, unborn: false, dirty: false, sync: '' };
  if (!status) return unreadable ? { ...base, kind: 'unknown', branch: '' } : null;
  if (status.state === 'unknown') return { ...base, kind: 'unknown', branch: '' };
  if (status.state !== 'ok') return null;
  const c = status.counts;
  const ahead = status.ahead ?? 0;
  const behind = status.behind ?? 0;
  const sync = (ahead > 0 ? `↑${ahead}` : '') + (behind > 0 ? `↓${behind}` : '');
  return {
    kind: 'branch',
    repo: roomy(CHIP_REPO_MIN) ? (status.repo_name ?? '') : '',
    branch: status.branch ?? (status.detached ? (status.head_short ?? '') : ''),
    detached: !!status.detached,
    unborn: !!status.unborn,
    dirty: roomy(CHIP_DOT_MIN) && c.staged + c.unstaged + c.untracked + c.conflicted > 0,
    sync: roomy(CHIP_SYNC_MIN) ? sync : '',
  };
}

export function chipTitle(
  status: SessionGitStatus | null,
  t: (key: string, params?: Record<string, unknown> | null) => string,
): string {
  if (!status || status.state !== 'ok') return t('git.chip.unknown_title');
  const c = status.counts;
  const lines: string[] = [];
  if (status.detached) lines.push(t('git.chip.detached', { sha: status.head_short ?? '' }));
  if (status.unborn) lines.push(t('git.chip.unborn'));
  lines.push(status.remote ? t('git.chip.remote', { name: status.remote }) + (status.upstream ? ` (${status.upstream})` : '') : t('git.chip.no_remote'));
  if ((status.ahead ?? 0) > 0) lines.push(t('git.chip.ahead', { n: status.ahead as number }));
  if ((status.behind ?? 0) > 0) lines.push(t('git.chip.behind', { n: status.behind as number }));
  lines.push(c.staged + c.unstaged + c.untracked + c.conflicted > 0 ? t('git.chip.dirty') : t('git.chip.clean'));
  return lines.join('\n');
}
