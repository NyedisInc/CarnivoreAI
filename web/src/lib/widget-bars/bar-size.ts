/* a little larger the bottom bar */
import type { RailEdge } from '../session-rail/rail-model';
import type { BarSize } from './bar-settings.svelte';
import { t } from '../i18n/index.svelte';

export const FOOT_H_PX = 20;

export const HANDLE_PX = 10;

export const RAIL_PIN_BOX_PX = 34;
export const RAIL_PIN_GLYPH_PX = 17;

export type BarLabelAt = 'none' | 'beside' | 'under';

export interface BarMetrics {
  readonly bar: number;
  readonly keyW: number | null;
  readonly keyH: number | null;
  readonly keyMinW: number;
  readonly keyMinH: number;
  readonly keyPad: string;
  readonly icon: number;
  readonly gap: number;
  readonly pad: number;
  readonly label: BarLabelAt;
  readonly labelMaxW: number;
}

const square = (key: number, icon: number, gap: number, pad: number, bar: number): BarMetrics => ({
  bar, keyW: key, keyH: key, keyMinW: 0, keyMinH: 0, keyPad: '0', icon, gap, pad, label: 'none', labelMaxW: 0,
});

export const BAR_SIZES: Readonly<Record<BarSize, Readonly<Record<RailEdge, BarMetrics>>>> = Object.freeze({
  compact: { side: square(16, 12, 2, 2, FOOT_H_PX), bottom: square(16, 12, 2, 2, FOOT_H_PX) },
  cozy: { side: square(28, 15, 4, 8, 36), bottom: square(28, 15, 4, 8, 36) },
  detailed: {
    side: { bar: 68, keyW: 60, keyH: null, keyMinW: 60, keyMinH: 46, keyPad: '6px 2px 4px', icon: 15, gap: 4, pad: 4, label: 'under', labelMaxW: 56 },
    bottom: { bar: 44, keyW: null, keyH: 32, keyMinW: 32, keyMinH: 0, keyPad: '0 10px', icon: 15, gap: 4, pad: 4, label: 'beside', labelMaxW: 0 },
  },
});

export function barThickness(edge: RailEdge, size: BarSize): number {
  return BAR_SIZES[size][edge].bar;
}

export function barLabel(manifest: { titleKey: string }): string {
  return t(manifest.titleKey);
}

const px = (n: number | null): string => (n === null ? 'auto' : `${n}px`);

export function barVars(edge: RailEdge, size: BarSize): string {
  const m = BAR_SIZES[size][edge];
  return `${edge === 'side' ? '--rail-w' : '--rail-h'}:${m.bar}px;--rail-key-w:${px(m.keyW)};--rail-key-h:${px(m.keyH)};`
    + `--rail-key-minw:${m.keyMinW}px;--rail-key-minh:${m.keyMinH}px;--rail-key-pad:${m.keyPad};--rail-gap:${m.gap}px;--rail-pad:${m.pad}px;`
    + `--rail-label-maxw:${m.labelMaxW}px;`;
}
