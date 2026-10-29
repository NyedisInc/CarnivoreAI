import { panelPins } from './panel-pins.svelte';
import { allocateLetters, pinnedAgent } from './pinned-scope';

let held: ReadonlyMap<number, string> = new Map();

export function pinLetter(row: number): string {
  held = allocateLetters(held, panelPins.rows().map((one) => ({ row: one, name: pinnedAgent(one).name })));
  return held.get(row) ?? '';
}
