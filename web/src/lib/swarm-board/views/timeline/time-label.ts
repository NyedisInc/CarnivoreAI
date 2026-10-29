import { t } from '../../../i18n/index.svelte';

const pad = (n: number): string => String(n).padStart(2, '0');

export function clock(ms: number): string {
  const d = new Date(ms);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function day(ms: number): string {
  const d = new Date(ms);
  return t('swarm.board.calendar.day_label', { weekday: t(`swarm.board.calendar.wd.${d.getDay()}`), date: pad(d.getDate()) });
}

export function stamp(ms: number): string {
  return `${day(ms)} ${clock(ms)}`;
}
