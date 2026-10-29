import { expect, test } from 'vitest';
import { buildTiles, visibleTiles } from './meta';
import type { ThemeManifest } from '../../api/types';

function manifest(source: string): ThemeManifest {
  return { id:'fixture-ascii', name:'oracle', source, description:'', author:null, version:null,
    cssVars:{'--color-bg-page':'#0d0a13','--color-border':'#3d314e','--color-accent':'#bf9bff','--ascii-display':'block'}, xterm:{} };
}

test('previews use the installed palette, builtin artwork and ASCII identity', () => {
  const [tile] = buildTiles([manifest('builtin')], null);
  expect(tile?.interior).toBe('#0d0a13');
  expect(tile?.rows[0].chip).toBe('#bf9bff');
  expect(tile?.artwork).toBe('/static/css/themes/fixture-ascii/preview.webp');
  expect(tile?.ascii).toBe(true);
});

test('installed catalog themes resolve their artwork under /themes/', () => {
  expect(buildTiles([manifest('user')], null)[0]?.artwork).toBe('/themes/fixture-ascii/preview.webp');
});

test('the favorites view keeps only starred themes; the all view keeps every one', () => {
  const two = [manifest('builtin'), { ...manifest('builtin'), id: 'nord', name: 'nord' }];
  expect(visibleTiles(two, null, 'favorites', ['nord']).map((tile) => tile.id)).toEqual(['nord']);
  expect(visibleTiles(two, null, 'favorites', []).map((tile) => tile.id)).toEqual([]);
  expect(visibleTiles(two, null, 'all', []).map((tile) => tile.id)).toEqual(['nord', 'fixture-ascii']);
});

test('the study placeholder tiles are never filtered by a star', () => {
  const placeholder = [{ ...manifest('builtin'), id: 'terminal', cssVars: {} }];
  expect(visibleTiles(placeholder, null, 'favorites', []).length).toBe(buildTiles(placeholder, null).length);
});

test('u159-01: an unsafe manifest value never reaches a live tile', () => {
  const hostile = { ...manifest('user'), cssVars: { '--color-bg-page': 'url(https://evil.example/x)', '--color-border': 'red; background:url(x)', '--color-accent': 'expression(1)' } };
  const [tile] = buildTiles([hostile], null);
  expect(tile?.interior).toBe('var(--oc-ground-panel)');
  expect(tile?.border).toBeUndefined();
  expect(tile?.rows[0].chip).toBe('var(--oc-text-dim)');
});

test('u159-02: the current tile is the page theme the click applies, not a session pin', () => {
  const two = [manifest('builtin'), { ...manifest('builtin'), id: 'nord', name: 'nord' }];
  expect(buildTiles(two, 'nord').map((tile) => [tile.id, tile.current])).toEqual([['nord', true], ['fixture-ascii', false]]);
  expect(buildTiles(two, null).some((tile) => tile.current)).toBe(false);
});
