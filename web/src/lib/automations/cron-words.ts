import { t } from '../i18n/index.svelte';
import { lowerWithMeridiem } from './logic/words';

const NUM = /^\d{1,2}$/;

function clock(hour: number, minute: number): string {
  return lowerWithMeridiem(new Date(2000, 0, 1, hour, minute).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }));
}

function weekday(day: number): string {
  return new Date(2000, 0, 2 + (day % 7)).toLocaleDateString(undefined, { weekday: 'short' });
}

export function cronWords(cron: string): string {
  const raw = t('automations.cadence', { cron });
  const f = cron.trim().split(/\s+/);
  if (f.length !== 5) return raw;
  const [min, hour, dom, mon, dow] = f as [string, string, string, string, string];
  if (mon !== '*') return raw;
  const step = /^\*\/(\d{1,2})$/.exec(min);
  if (step && hour === '*' && dom === '*' && dow === '*') return t('automations.cadence_words.every_minutes', { count: Number(step[1]) });
  if (!NUM.test(min) || Number(min) > 59) return raw;
  if (hour === '*' && dom === '*' && dow === '*') return t('automations.cadence_words.hourly', { minute: min.padStart(2, '0') });
  if (!NUM.test(hour) || Number(hour) > 23) return raw;
  const time = clock(Number(hour), Number(min));
  if (dom === '*' && dow === '*') return t('automations.cadence_words.daily', { time });
  const nth = /^(\d)#([1-5])$/.exec(dow);
  if (dom === '*' && nth && Number(nth[1]) <= 7) {
    return t('automations.cadence_words.nth_weekday', { nth: t(`automations.simple.ordinal.${nth[2]}`), day: t(`automations.simple.day.${Number(nth[1]) % 7}`), time });
  }
  if (dom === '*' && dow === '1-5') return t('automations.cadence_words.weekdays', { time });
  if (dom === '*' && NUM.test(dow) && Number(dow) <= 7) return t('automations.cadence_words.weekly', { day: weekday(Number(dow)), time });
  if (dow === '*' && NUM.test(dom) && Number(dom) >= 1 && Number(dom) <= 31) return t('automations.cadence_words.monthly', { day: Number(dom), time });
  return raw;
}
