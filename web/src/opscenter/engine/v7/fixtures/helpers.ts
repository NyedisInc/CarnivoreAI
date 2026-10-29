
import type { SlotId } from '../../types';

export function term(name: string): SlotId {
  return `terminal:${name}` as SlotId;
}

export function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}
