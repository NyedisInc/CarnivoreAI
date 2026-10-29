
import { t } from '../../lib/i18n/index.svelte';

export function elapsed(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = whole % 60;
  if (hours > 0) {
    return t('opscenter.time.elapsed_hours', {
      hours,
      minutes: String(minutes).padStart(2, '0'),
    });
  }
  return t('opscenter.time.elapsed_minutes', {
    minutes,
    seconds: String(rest).padStart(2, '0'),
  });
}

export function relative(minutes: number): string {
  const whole = Math.max(0, Math.floor(minutes));
  if (whole < 60) return t('opscenter.time.ago_minutes', { count: whole });
  if (whole < 60 * 24) return t('opscenter.time.ago_hours', { count: Math.floor(whole / 60) });
  return t('opscenter.time.ago_days', { count: Math.floor(whole / (60 * 24)) });
}

export function leftTruncate(value: string, max: number): string {
  if (max <= 1 || value.length <= max) return value;
  return `…${value.slice(value.length - (max - 1))}`;
}

export function compact(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 10_000) return `${(value / 1000).toFixed(1)}K`;
  return String(value);
}

const HAS_ZONE_MARKER = /(?:Z|z|[+-]\d{2}:?\d{2})$/;

/* could not */
export function parseServerTime(value: string | null | undefined): number {
  if (typeof value !== 'string') return Number.NaN;
  const trimmed = value.trim();
  if (!trimmed) return Number.NaN;
  return Date.parse(HAS_ZONE_MARKER.test(trimmed) ? trimmed : `${trimmed}Z`);
}

export function clockTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase();
}
