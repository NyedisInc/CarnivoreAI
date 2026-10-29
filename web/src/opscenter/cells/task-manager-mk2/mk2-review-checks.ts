import type { ReviewCheckRow } from '../../../cplugs/huddle/huddle-model';

export function tickedLine(check: ReviewCheckRow, say: (key: string, args: Record<string, string>) => string): string {
  if (!check.checked) return '';
  const when = check.checked_at === null ? '' : new Date(check.checked_at * 1000).toLocaleString();
  return say('opscenter.cell.task_manager_mk2.check_ticked_by', { who: check.checked_by ?? '', when }).trim();
}
