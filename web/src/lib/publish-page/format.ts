import type { Translate } from '../sessions/types';

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'] as const;
const MINUTE = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;

export function toDate(stamp: string | number | null | undefined): Date | null {
    if (stamp === null || stamp === undefined || stamp === '') return null;
    const date = new Date(stamp);
    return Number.isNaN(date.getTime()) ? null : date;
}

export function dateText(stamp: string | number | null | undefined, t: Translate): string {
    const date = toDate(stamp);
    if (!date) return '';
    return t('publish.page.date.day_month', { day: date.getDate(), month: t(`publish.page.month.${MONTHS[date.getMonth()]}`) });
}

export function clockText(stamp: string | number | null | undefined, t: Translate): string {
    const date = toDate(stamp);
    if (!date) return '';
    const pad = (n: number): string => (n < 10 ? `0${n}` : String(n));
    return t('publish.page.date.clock', { hh: pad(date.getHours()), mm: pad(date.getMinutes()) });
}

export function agoText(stamp: string | number | null | undefined, now: number, t: Translate): string {
    const date = toDate(stamp);
    if (!date) return '';
    const gap = now - date.getTime();
    if (gap < MINUTE) return t('publish.page.time.just_now');
    if (gap < HOUR) return t('publish.page.time.minutes_ago', { count: Math.floor(gap / MINUTE) });
    if (gap < DAY) return t('publish.page.time.hours_ago', { count: Math.floor(gap / HOUR) });
    return t('publish.page.time.days_ago', { count: Math.floor(gap / DAY) });
}

export function groupedNumber(n: number): string {
    return String(Math.max(0, Math.trunc(n))).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

export function bytesText(bytes: number, t: Translate): string {
    return t('publish.page.size.bytes', { bytes: groupedNumber(bytes) });
}

export function kibText(bytes: number, t: Translate): string {
    const kib = Math.round((Math.max(0, bytes) / 1024) * 10) / 10;
    return t('publish.page.size.kib', { value: kib });
}
