
export interface RoundTarget { slug: string; revision: string }

export type RoundOpener = (round: RoundTarget) => Promise<void>;

let opener: RoundOpener | null = null;

export function registerRoundOpener(fn: RoundOpener): void {
  opener = fn;
}

export function roundOpener(): RoundOpener | null {
  return opener;
}

export function resetRoundOpener(): void {
  opener = null;
}
