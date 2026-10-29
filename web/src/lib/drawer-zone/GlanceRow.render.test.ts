/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { LedgerSnapshot } from '../../opscenter/api/types';

const fakeLedger = vi.hoisted(() => ({ status: 'ok' as const, data: null as LedgerSnapshot | null, fetchedAt: null as number | null, error: null as string | null }));
vi.mock('../../opscenter/api', async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), ledger: fakeLedger }));

import GlanceRow from './GlanceRow.svelte';
import { GLANCE_TILE_HEIGHT_PX, GLANCE_TILE_WIDTH_PX } from './glance';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';

const HOUR = 3600_000;
const win = (kind: string, label: string, used: number, seconds: number, leftMs: number) => ({ kind, label, used_pct: used, window_seconds: seconds, resets_at: new Date(Date.now() + leftMs).toISOString() });
const acct = (id: string, provider: string, used5h: number) => ({
  id, name: id, short_name: null, provider, plan: 'max', identity: id, credential_state: 'ok', fetched_at: null, next_poll_at: null, error: null, color: null, managed: false,
  windows: [win('five_hour', '5h', used5h, 5 * 3600, 4 * HOUR), win('seven_day', '7d', 40, 7 * 86400, 84 * HOUR)],
});
const snapshot = (accounts: unknown[]): LedgerSnapshot => ({ accounts, total: { accounts: accounts.length, windows: [] }, loop: { alive: true, last_pass_at: null } }) as LedgerSnapshot;

let host: HTMLElement;
let instance: unknown;
const opened = vi.fn();
const draw = (...widgets: string[]): void => {
  instance = mount(GlanceRow, { target: host, props: { entries: widgets.map((w) => ({ key: w, widget: w, manifest: CORE_MANIFESTS[w]! })), onopen: opened } });
  flushSync();
};

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  opened.mockClear();
});
afterEach(() => {
  unmount(instance as never);
  host.remove();
});

describe('the mini row', () => {
  test('the glance tile is HALF the first cut: 64 wide, 36 tall (was 128 by 72)', () => {
    expect(GLANCE_TILE_WIDTH_PX).toBe(128 / 2);
    expect(GLANCE_TILE_HEIGHT_PX).toBe(72 / 2);
  });

  test('draws one tile per entry the widget lists (N accounts, N tiles), each in a 64 by 36 box, with an amber bar only when ahead', () => {
    fakeLedger.data = snapshot([acct('a', 'claude', 40), acct('a2', 'claude', 5), acct('b', 'codex', 10)]);
    draw('core.ledger');
    const tiles = [...host.querySelectorAll<HTMLElement>('[data-glance-tile]')];
    expect(tiles.map((tile) => tile.dataset['glanceTile'])).toEqual(['a', 'a2', 'b']);
    expect(tiles.map((tile) => tile.querySelector('[data-account-label]')!.textContent)).toEqual(['a', 'a2', 'b']);
    expect(tiles.every((tile) => tile.style.height === '36px' && tile.style.width === '64px')).toBe(true);
    const scales = (tile: HTMLElement): (string | null)[] => [...tile.querySelectorAll('.oc-gauge')].map((g) => g.getAttribute('data-scale'));
    expect(scales(tiles[0]!)).toEqual(['3', '1']);
    expect(scales(tiles[1]!)).toEqual(['1', '1']);
    expect(scales(tiles[2]!)).toEqual(['1', '1']);
    expect(tiles[0]!.querySelector('.pgl')!.getAttribute('title')).toContain('40%');
    expect(tiles[0]!.querySelectorAll('.oc-gauge__pace')).toHaveLength(2);
    expect(host.querySelector('.dz-glance--icon')).toBeNull();
  });

  test('a tile names the account it speaks for, clipped, with the whole name in its title', () => {
    fakeLedger.data = snapshot([{ ...acct('a', 'claude', 30), name: 'second account', short_name: 'second' }]);
    draw('core.ledger');
    const tile = host.querySelector<HTMLElement>('.pgl')!;
    expect(tile.querySelector('[data-account-label]')!.textContent).toBe('second');
    expect(tile.getAttribute('title')).toContain('second account');
    expect(tile.getAttribute('title')).toContain('claude max');
  });

  test('the provider mark draws when the legacy icon module is loaded (it is in the app and the harness)', () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    new Function(readFileSync(join(__dirname, '..', '..', '..', '..', 'client', 'js', 'agent-family-icon.js'), 'utf8'))();
    fakeLedger.data = snapshot([acct('a', 'claude', 30)]);
    draw('core.ledger');
    const mark = host.querySelector<HTMLElement>('.pgl [data-provider-mark]')!;
    expect(mark.dataset['providerMark']).toBe('claude');
    expect(mark.querySelector('svg')).not.toBeNull();
  });

  test('a press on a tile opens the area', () => {
    fakeLedger.data = snapshot([acct('a', 'claude', 30)]);
    draw('core.ledger');
    host.querySelector<HTMLButtonElement>('.pgl')!.click();
    expect(opened).toHaveBeenCalledOnce();
  });

  test('draws the icon for a widget with no glance, beside the tiles of one that has', () => {
    fakeLedger.data = snapshot([acct('a', 'claude', 10)]);
    draw('core.ledger', 'core.notes');
    expect(host.querySelectorAll('[data-glance-tile]')).toHaveLength(1);
    const icon = host.querySelector<HTMLButtonElement>('[data-zone-glance="core.notes"]')!;
    expect(icon.classList.contains('dz-glance--icon')).toBe(true);
    expect(icon.style.width, 'a tile the same glance size, its icon inside').toBe('64px');
    expect(icon.style.height).toBe('36px');
    expect(icon.querySelector('svg')).not.toBeNull();
    icon.click();
    expect(opened).toHaveBeenCalledOnce();
  });

  test('falls back to the icon when the provider widget has nothing to show', () => {
    fakeLedger.data = snapshot([]);
    draw('core.ledger');
    expect(host.querySelector('[data-glance-tile]')).toBeNull();
    expect(host.querySelector('[data-zone-glance="core.ledger"].dz-glance--icon')).not.toBeNull();
  });
});
