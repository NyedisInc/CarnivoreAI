import { t } from '../i18n/index.svelte';

const KEYS: Record<string, string> = {
  needs_update: 'pack.autodelegate.off.code.needs_update', no_record: 'pack.autodelegate.off.code.no_record',
  not_a_copy: 'pack.autodelegate.off.code.not_a_copy', job_running: 'pack.autodelegate.off.code.job_running',
  session_live: 'pack.autodelegate.off.code.session_live', dirty: 'pack.autodelegate.off.code.dirty',
  stash: 'pack.autodelegate.off.code.stash', unseen_commits: 'pack.autodelegate.off.code.unseen_commits',
  worktrees: 'pack.autodelegate.off.code.worktrees', git_failed: 'pack.autodelegate.off.code.git_failed',
  too_many_refs: 'pack.autodelegate.off.code.too_many_refs', no_trash: 'pack.autodelegate.off.code.no_trash',
  other_volume: 'pack.autodelegate.off.code.other_volume', unreachable: 'pack.autodelegate.off.code.unreachable',
  machine_unreachable: 'pack.autodelegate.off.code.unreachable', timeout: 'pack.autodelegate.off.code.timeout',
  refused: 'pack.autodelegate.off.code.refused', bad_answer: 'pack.autodelegate.off.code.bad_answer',
  row_left: 'pack.autodelegate.off.code.row_left', not_chosen: 'pack.autodelegate.off.code.not_chosen',
  unknown: 'pack.autodelegate.off.code.unknown',
};

export const reasonFor = (code: string): string => t(KEYS[code] ?? 'pack.autodelegate.off.code.generic');
