
import { pickState, atLeast } from '../../lib/states';
import type { CellSize } from '../../engine/types';

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
