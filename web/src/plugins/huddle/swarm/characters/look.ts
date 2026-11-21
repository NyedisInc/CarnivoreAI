import type { CharacterState } from './states';

export const SERIES_COUNT = 8;

export function hashSeed(seed: string | number): number {
  const s = String(seed);
  let h = 7;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export function seriesIndex(seed: string | number, shift = 0): number {
  return 1 + ((hashSeed(seed) + shift) % SERIES_COUNT);
}

export function seriesVar(index: number): string {
  const i = Math.min(SERIES_COUNT, Math.max(1, Math.round(index)));
  return `var(--oc-series-${i})`;
}

export interface RibbonSlot {
  t: number;
  rx: number;
  d: number;
  R: number;
  dir: 'normal' | 'reverse';
  a0: number;
}

export const RIBBON_TURN_SCALE = 0.6;

export const MOCKUP_TURN_SECONDS: readonly number[] = [2.6, 3.3, 4.1];

export const RIBBON_SLOTS: readonly RibbonSlot[] = [
  { t: -16, rx: 64, d: Math.round(MOCKUP_TURN_SECONDS[0]! * RIBBON_TURN_SCALE * 1000) / 1000, a0: 30, R: 0.62, dir: 'normal' },
  { t: 26, rx: 60, d: Math.round(MOCKUP_TURN_SECONDS[1]! * RIBBON_TURN_SCALE * 1000) / 1000, a0: 150, R: 0.68, dir: 'reverse' },
  { t: 72, rx: 68, d: Math.round(MOCKUP_TURN_SECONDS[2]! * RIBBON_TURN_SCALE * 1000) / 1000, a0: 260, R: 0.58, dir: 'normal' },
];

export function contrastIndex(n: number): number {
  return ((Math.min(SERIES_COUNT, Math.max(1, Math.round(n))) + 3) % SERIES_COUNT) + 1;
}

export interface Ribbon {
  slot: RibbonSlot;
  color: string;
}

export function ribbonsFor(state: CharacterState, bodyIndex: number, subs: readonly (string | number)[] = []): Ribbon[] {
  const own = (n: number): string => {
    const c = contrastIndex(n);
    return seriesVar(c === bodyIndex ? (c % SERIES_COUNT) + 1 : c);
  };
  if (state === 'working') return [{ slot: RIBBON_SLOTS[0]!, color: own(bodyIndex) }];
  if (state !== 'working_subagent') return [];
  if (subs.length === 0) return [{ slot: RIBBON_SLOTS[0]!, color: own(bodyIndex) }];
  return subs.slice(0, 3).map((s, i) => ({ slot: RIBBON_SLOTS[i]!, color: own(seriesIndex(s)) }));
}

export function stateLabelKey(state: CharacterState): string {
  return `cplug.huddle.swarm.state.${state}`;
}
