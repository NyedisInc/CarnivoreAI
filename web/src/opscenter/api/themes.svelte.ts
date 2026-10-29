
import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import type { ThemeManifest } from './types';
import { themes as demoTiles } from '../data/themes';

export const THEMES_POLL_MS = 24 * 60 * 60 * 1000;

function demoThemes(): ThemeManifest[] {
  return demoTiles.map((tile) => ({
    id: tile.id,
    name: tile.name,
    description: '',
    author: null,
    version: null,
    cssVars: {},
    xterm: {},
    source: 'builtin',
  }));
}

export const themes: Resource<ThemeManifest[]> = resource<ThemeManifest[]>(
  () => authFetch<ThemeManifest[]>('/themes'),
  { intervalMs: THEMES_POLL_MS, name: 'themes', demo: demoThemes },
);
