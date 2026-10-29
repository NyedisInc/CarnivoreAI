
import { pickState, atLeast } from '../../lib/states';
import type { CellSize } from '../../engine/types';

/* flex: 0 0 auto`) paint straight through the account
 * window beside it, at a width `scrollWidth - clientWidth` read as ZERO,
 * because nothing about that overlap made the ROW any wider. The fix
 * lives in the stylesheet (`.oc-tf-model` and `.oc-tf-meter` both keep
 * their flex default `min-width: auto` now, never `0`, so a group's own
 * box can never shrink below what its non-shrinking children need); padding */
export const FOOT_STEPS: readonly CellSize[] = [
  { name: 'core', min: 0 },
  { name: 'bars', min: 440 },
  { name: 'effort', min: 520 },
  { name: 'tokens', min: 1080 },
  { name: 'reset', min: 1320 },
];

export interface FootSplit {
  state: string;
  bars: boolean;
  effort: boolean;
  tokens: boolean;
  reset: boolean;
}

export function splitFoot(width: number, previous?: string): FootSplit {
  const state = pickState(FOOT_STEPS, width, previous);
  return {
    state,
    bars: atLeast(FOOT_STEPS, state, 'bars'),
    effort: true,
    tokens: atLeast(FOOT_STEPS, state, 'tokens'),
    reset: atLeast(FOOT_STEPS, state, 'reset'),
  };
}
