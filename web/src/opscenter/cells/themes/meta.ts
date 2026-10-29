/* --color- */

import { metaFor } from '../../engine/meta';
import { themes as demoTiles } from '../../data/themes';
import type { ThemeManifest, SessionInfo } from '../../api';
import type { PhoneSummary } from '../../engine/types';
import { themes as themesResource, sessions } from '../../api';
import { parseServerTime } from '../../lib/format';
import { t } from '../../../lib/i18n/index.svelte';
import { themeAssetBase } from '../../../lib/themes-page/asset-base';
import { themeFavorites } from '../../../lib/themes-page/favorites.svelte';
import { themesCellView, type ThemesCellView } from './view.svelte';

export const meta = metaFor('themes');

export const tile = { width: 86, gap: 24, height: 60, label: 26 };

export interface TileRow {
  chipTop: number;
  chipHeight: number;
  lineTop: number;
  lineWidth: number;
}

export const CHIP_LEFT = 11;
export const CHIP_WIDTH = 6;
export const LINE_LEFT = 18;
export const LINE_HEIGHT = 2;

export const tileRows: TileRow[] = [
  { chipTop: 11, chipHeight: 6, lineTop: 14, lineWidth: 24 },
  { chipTop: 22, chipHeight: 5, lineTop: 23, lineWidth: 54 },
  { chipTop: 31, chipHeight: 5, lineTop: 32, lineWidth: 32 },
  { chipTop: 38, chipHeight: 4, lineTop: 39, lineWidth: 0 },
  { chipTop: 45, chipHeight: 4, lineTop: 46, lineWidth: 0 },
];

export const TILES_PER_ROW: Record<string, number> = {
  'tiles-2': 2,
  'tiles-3': 3,
  'tiles-4': 4,
  'tiles-5': 5,
  'tiles-6': 6,
};

export interface RenderRow {
  chip: string;
  line?: string;
}

export interface RenderTile {
  id: string;
  name: string;
  current: boolean;
  interior: string;
  border?: string;
  artwork?: string;
  ascii?: boolean;
  rows: [RenderRow, RenderRow, RenderRow, RenderRow, RenderRow];
}

const ROW_VARS = ['--color-accent', '--color-success', '--color-warning', '--color-danger', '--color-fg'] as const;

const INTERIOR_VARS = ['--color-bg-page', '--color-bg'] as const;

const ROW_FALLBACK = 'var(--oc-text-dim)';

const INTERIOR_FALLBACK = 'var(--oc-ground-panel)';

function firstOf(cssVars: Record<string, string>, names: readonly string[]): string | undefined {
  for (const name of names) {
    const value = cssVars[name];
    if (value) return value;
  }
  return undefined;
}

function liveTile(manifest: ThemeManifest, current: boolean): RenderTile {
  const palette = ROW_VARS.map((name) => manifest.cssVars[name]).filter((value): value is string => Boolean(value));
  const rowColor = (index: number): string => (palette.length ? (palette[index % palette.length] as string) : ROW_FALLBACK);
  return {
    id: manifest.id,
    name: manifest.name,
    current,
    interior: firstOf(manifest.cssVars, INTERIOR_VARS) ?? INTERIOR_FALLBACK,
    border: manifest.cssVars['--color-border'],
    artwork: `${themeAssetBase(manifest.source, manifest.id)}/preview.webp`,
    ascii: manifest.cssVars['--ascii-display'] === 'block',
    rows: [0, 1, 2, 3, 4].map((index) => ({ chip: rowColor(index), line: rowColor(index) })) as RenderTile['rows'],
  };
}

function demoTile(id: string): RenderTile | null {
  const found = demoTiles.find((tile) => tile.id === id);
  if (!found) return null;
  return {
    id: found.id,
    name: found.name,
    current: found.current,
    interior: `var(${found.interior})`,
    border: `var(${found.border})`,
    rows: found.rows.map((row) => ({
      chip: `var(${row.chip})`,
      line: row.line ? `var(${row.line})` : undefined,
    })) as RenderTile['rows'],
  };
}

export function currentThemeId(rows: SessionInfo[] | null): string | null {
  if (!rows || !rows.length) return null;
  let bestId: string | null = null;
  let bestAt = -Infinity;
  for (const row of rows) {
    if (!row.pinned_theme) continue;
    const at = parseServerTime(row.session.last_activity);
    const when = Number.isFinite(at) ? at : -Infinity;
    if (when > bestAt) {
      bestAt = when;
      bestId = row.pinned_theme;
    }
  }
  return bestId;
}

export function buildTiles(manifests: ThemeManifest[] | null, sessionRows: SessionInfo[] | null): RenderTile[] {
  if (!manifests || !manifests.length) return [];
  if (isStudyPlaceholder(manifests)) {
    return manifests.map((manifest) => demoTile(manifest.id)).filter((tile): tile is RenderTile => tile !== null);
  }
  const currentId = currentThemeId(sessionRows);
  const sorted = [...manifests].sort((a, b) => {
    if (a.source === 'builtin' && b.source !== 'builtin') return -1;
    if (b.source === 'builtin' && a.source !== 'builtin') return 1;
    return a.name.localeCompare(b.name);
  });
  return sorted.map((manifest) => liveTile(manifest, manifest.id === currentId));
}

function isStudyPlaceholder(manifests: ThemeManifest[]): boolean {
  return manifests.every((manifest) => Object.keys(manifest.cssVars).length === 0);
}

export function visibleTiles(
  manifests: ThemeManifest[] | null,
  sessionRows: SessionInfo[] | null,
  view: ThemesCellView,
  favorites: readonly string[],
): RenderTile[] {
  const tiles = buildTiles(manifests, sessionRows);
  if (view !== 'favorites' || !manifests || isStudyPlaceholder(manifests)) return tiles;
  return tiles.filter((tile) => favorites.includes(tile.id));
}

export function titleCount(): number | null {
  if (themesResource.status !== 'ok') return null;
  return visibleTiles(themesResource.data, sessions.data, themesCellView.value, themeFavorites.ids).length;
}

export function phoneSummary(): PhoneSummary | null {
  if (themesResource.status !== 'ok') return null;
  const tiles = buildTiles(themesResource.data, sessions.data);
  const current = tiles.find((t) => t.current);
  return {
    marks: [],
    note: current
      ? current.name
      : tiles.length
        ? t('opscenter.themes.none_pinned')
        : t('opscenter.themes.none'),
  };
}
