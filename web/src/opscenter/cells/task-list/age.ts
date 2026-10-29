import { t } from '../../../lib/i18n/index.svelte';
import { messageTime } from '../../../cplugs/huddle/huddle-model';

const MINUTE_S = 60;
const HOUR_S = 3600;
const DAY_S = 86_400;
const WEEK_S = 604_800;

export function ageWords(atMs: number, nowMs: number, scheduled: boolean): string {
  if (scheduled) return messageTime(atMs / 1000, nowMs / 1000);
  const s = Math.max(0, Math.round((nowMs - atMs) / 1000));
  if (s < MINUTE_S) return t('opscenter.cell.task_list.age_s', { n: s });
  if (s < HOUR_S) return t('opscenter.cell.task_list.age_m', { n: Math.floor(s / MINUTE_S) });
  if (s < DAY_S) return t('opscenter.cell.task_list.age_h', { n: Math.floor(s / HOUR_S) });
  if (s < WEEK_S) return t('opscenter.cell.task_list.age_d', { n: Math.floor(s / DAY_S) });
  return t('opscenter.cell.task_list.age_w', { n: Math.floor(s / WEEK_S) });
}
