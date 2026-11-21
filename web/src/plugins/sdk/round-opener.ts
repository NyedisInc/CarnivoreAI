
export interface RoundTarget { slug: string; revision: string }

export type RoundOpener = (round: RoundTarget) => Promise<void>;

import { SvelteMap } from 'svelte/reactivity';

let opener: RoundOpener | null = null;
const changes = new SvelteMap<'v', number>([['v', 0]]);
function bump(): void {
  changes.set('v', (changes.get('v') ?? 0) + 1);
}
let isOn: () => boolean = () => true;

export function registerRoundOpener(fn: RoundOpener, enabled: () => boolean = () => true): void {
  opener = fn;
  isOn = enabled;
  bump();
}

export function roundOpener(): RoundOpener | null {
  void changes.get('v');
  return opener !== null && isOn() ? opener : null;
}

export function resetRoundOpener(): void {
  opener = null;
  isOn = () => true;
  bump();
}
