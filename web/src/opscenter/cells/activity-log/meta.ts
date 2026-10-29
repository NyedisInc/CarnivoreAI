
import { metaFor } from '../../engine/meta';
import { activity, transport } from '../../api';
import type { ColumnSpec, PhoneSummary } from '../../engine/types';
import { t } from '../../../lib/i18n/index.svelte';

export const meta = metaFor('activity-log');

/* padding */
export const columns: ColumnSpec[] = [
  { key: 'time', headKey: 'opscenter.column.time', minPx: 72, weight: 0 },
  { key: 'tag', headKey: 'opscenter.column.tag', minPx: 69, weight: 0 },
  { key: 'message', headKey: 'opscenter.column.message', minPx: 180, weight: 4 },
  { key: 'source', headKey: 'opscenter.column.source', minPx: 90, weight: 1 },
];

export const sourceFullMinPx = 150;

export const rowHeight = 15;

/* padding */
export const ROW_PAD_LEFT = 15;
export const ROW_PAD_RIGHT = 10;
export const ROW_GAP = 18;

export function titleSuffix(): string | null {
  if (transport.state === 'unknown') return null;
  return transport.state === 'connected'
    ? t('opscenter.activity.suffix_live')
    : t('opscenter.activity.suffix_other', { state: transport.state });
}

export function onRightControl(): void {
  activity.lines = [];
}

export function phoneTotal(): number | null {
  return activity.lines.length;
}

export function phoneSummary(): PhoneSummary | null {
  const newest = activity.lines.length
    ? activity.lines.reduce((held, line) => (line.time > held.time ? line : held))
    : null;
  const live = transport.state === 'connected';
  return {
    marks: [
      {
        tone: live ? 'oc-green-bright' : 'oc-text-dim',
        shape: live ? 'solid' : 'hollow',
        count: null,
        label: live
          ? t('opscenter.activity.channel_connected')
          : t('opscenter.activity.channel_other', { state: transport.state }),
      },
    ],
    note: newest ? newest.time.slice(0, 5) : t('opscenter.activity.nothing_yet'),
  };
}
