
import type { CellSize } from '../engine/types';

export const HYSTERESIS = 12;

export function pickState(steps: readonly CellSize[], px: number, previous?: string): string {
  if (!steps.length) return '';
  const first = steps[0];
  if (!first) return '';
  let chosen = first.name;
  for (const step of steps) {
    if (px >= step.min) chosen = step.name;
  }
  if (previous && previous !== chosen) {
    const held = steps.find((step) => step.name === previous);
    const wanted = steps.find((step) => step.name === chosen);
    if (held && wanted && held.min > wanted.min && px >= held.min - HYSTERESIS) return previous;
  }
  return chosen;
}

export function atLeast(steps: readonly CellSize[], current: string, name: string): boolean {
  const here = steps.findIndex((step) => step.name === current);
  const asked = steps.findIndex((step) => step.name === name);
  return here >= 0 && asked >= 0 && here >= asked;
}
