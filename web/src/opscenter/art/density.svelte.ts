import { readMigrating, writeMigrating } from '../../lib/browser-storage-migrate';

export const DENSITIES = ['minimal', 'balanced', 'full'] as const;
export type ArtDensity = typeof DENSITIES[number];
const KEY = 'carnivore.art-density.v1';
export const artDensity = $state<{ value: ArtDensity }>({ value: 'balanced' });
let loaded = false;

export function validDensity(value: unknown): ArtDensity {
  return DENSITIES.includes(value as ArtDensity) ? value as ArtDensity : 'balanced';
}

export function loadArtDensity(): void {
  if (loaded || typeof document === 'undefined') return;
  loaded = true;
  try { artDensity.value = validDensity(readMigrating(KEY)); }
  catch {  }
  document.documentElement.dataset.artDensity = artDensity.value;
}

export function setArtDensity(value: unknown): void {
  artDensity.value = validDensity(value);
  document.documentElement.dataset.artDensity = artDensity.value;
  try { writeMigrating(KEY, artDensity.value); }
  catch {  }
}
