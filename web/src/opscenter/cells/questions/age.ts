import { t } from '../../../lib/i18n/index.svelte';

export function ageText(atMs: number, nowMs: number): string {
  const s = Math.max(0, Math.round((nowMs - atMs) / 1000));
  if (s < 60) return t('drawer.questions.age_s', { n: s });
  if (s < 3600) return t('drawer.questions.age_m', { n: Math.floor(s / 60) });
  return t('drawer.questions.age_h', { n: Math.floor(s / 3600) });
}
