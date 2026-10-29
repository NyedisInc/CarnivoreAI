import type { UsageMeter, UsageWindowView } from '../../api';
import type { FootFeature } from './foot-plan';

export type Admit = Record<FootFeature, boolean>;

export function fillPct(meter: UsageMeter): number {
  return meter.segments > 0 ? (meter.filled / meter.segments) * 100 : 0;
}

export function resetFeature(w: UsageWindowView): FootFeature {
  return w.key === 'window:five_hour' ? 'reset5h' : 'reset7d';
}
