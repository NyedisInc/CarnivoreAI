
export interface RoundTarget { slug: string; revision: string }

export type RoundOpener = (round: RoundTarget) => Promise<void>;

let opener: RoundOpener | null = null;
let isOn: () => boolean = () => true;

export function registerRoundOpener(fn: RoundOpener, enabled: () => boolean = () => true): void {
  opener = fn;
  isOn = enabled;
}

export function roundOpener(): RoundOpener | null {
  return opener !== null && isOn() ? opener : null;
}

export function resetRoundOpener(): void {
  opener = null;
  isOn = () => true;
}
