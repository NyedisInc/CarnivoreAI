/* could not measure */

import { metaFor } from '../../engine/meta';
import { t } from '../../../lib/i18n/index.svelte';
import type { MachineStats } from './store.svelte';

export const meta = metaFor('machine-stats');

export const WARN_PERCENT = 75;
export const HOT_PERCENT = 90;

export function toneOf(percent: number): 'ok' | 'warn' | 'hot' {
  if (percent >= HOT_PERCENT) return 'hot';
  return percent >= WARN_PERCENT ? 'warn' : 'ok';
}

export interface Reading {
  key: 'cpu' | 'memory' | 'disk' | 'load' | 'uptime';
  label: string;
  figure: string;
  percent: number | null;
  sub: string;
  measured: boolean;
}

export function sizeText(bytes: number): string {
  const gb = bytes / 1e9;
  return gb >= 1000
    ? t('opscenter.machine_stats.tb', { value: (gb / 1000).toFixed(1) })
    : t('opscenter.machine_stats.gb', { value: gb >= 100 ? gb.toFixed(0) : gb.toFixed(1) });
}

export function uptimeText(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return t('opscenter.machine_stats.up_days', { days: String(days), hours: String(hours) });
  if (hours > 0) return t('opscenter.machine_stats.up_hours', { hours: String(hours), minutes: String(minutes) });
  return t('opscenter.machine_stats.up_minutes', { minutes: String(minutes) });
}

export function readings(stats: MachineStats): Reading[] {
  const none = t('opscenter.value.not_measured');
  const pct = (value: number | null): string => (value === null ? none : t('opscenter.machine_stats.percent', { value: String(Math.round(value)) }));
  const used = stats.memory_used_bytes !== null && stats.memory_total_bytes !== null
    ? t('opscenter.machine_stats.memory_of', { used: sizeText(stats.memory_used_bytes), total: sizeText(stats.memory_total_bytes) })
    : '';
  return [
    {
      key: 'cpu', label: t('opscenter.machine_stats.cpu'), figure: pct(stats.cpu_percent), percent: stats.cpu_percent, measured: stats.cpu_percent !== null,
      sub: stats.cpu_count ? t('opscenter.machine_stats.cores', { count: String(stats.cpu_count) }) : '',
    },
    { key: 'memory', label: t('opscenter.machine_stats.memory'), figure: pct(stats.memory_percent), percent: stats.memory_percent, sub: used,
      measured: stats.memory_percent !== null },
    {
      key: 'disk', label: t('opscenter.machine_stats.disk'), figure: pct(stats.disk_percent), percent: stats.disk_percent, measured: stats.disk_percent !== null,
      sub: stats.disk_free_bytes === null ? '' : t('opscenter.machine_stats.disk_free', { free: sizeText(stats.disk_free_bytes) }),
    },
    {
      key: 'load', label: t('opscenter.machine_stats.load'), figure: stats.load_1 === null ? none : stats.load_1.toFixed(2), percent: null, measured: stats.load_1 !== null,
      sub: stats.load_5 === null || stats.load_15 === null
        ? ''
        : t('opscenter.machine_stats.load_sub', { five: stats.load_5.toFixed(2), fifteen: stats.load_15.toFixed(2) }),
    },
    {
      key: 'uptime', label: t('opscenter.machine_stats.uptime'),
      figure: stats.uptime_seconds === null ? none : uptimeText(stats.uptime_seconds), percent: null, sub: '',
      measured: stats.uptime_seconds !== null,
    },
  ];
}
