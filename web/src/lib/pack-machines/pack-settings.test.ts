import { describe, expect, test } from 'vitest';

import { filledCells, linkMarkFor, linkStateOf, loadPercent, reserveCells } from './pack-meter-math';
import { PACK_TABS, packTabOf } from '../pack-page/pack-hash';

describe('the meter and link arithmetic', () => {
  test('known values', () => {
    expect(filledCells(50)).toBe(10);
    expect(filledCells(null)).toBe(0);
    expect(reserveCells(10)).toBe(2);
    expect(loadPercent(5, 10)).toBe(50);
    expect(loadPercent(null, 10)).toBeNull();
    expect(linkStateOf('connected')).toBe('linked');
    expect(linkStateOf('waiting')).toBe('connecting');
    expect(linkStateOf('refused')).toBe('error');
    expect(linkStateOf('disconnected')).toBe('down');
    const snap = {};
    expect(linkMarkFor({ state: 'connected', snapshot: snap, age_seconds: 2 })).toBe('linked');
    expect(linkMarkFor({ state: 'connected', snapshot: null, age_seconds: null })).toBe('down');
    expect(linkMarkFor({ state: 'connected', snapshot: snap, age_seconds: 31 })).toBe('down');
    expect(linkMarkFor({ state: 'waiting', snapshot: null, age_seconds: null })).toBe('connecting');
  });
});

describe('the tab and hash mapping', () => {
  test('four tabs; #pack, #hosts and the old settings addresses reach the Pack page; old slugs map to the new tabs (ssh ones open the ssh filter)', () => {
    expect([...PACK_TABS]).toEqual(['computers', 'work', 'logins', 'skills']);
    expect(packTabOf('#pack')).toEqual({ tab: null, ssh: false });
    expect(packTabOf('#hosts')).toEqual({ tab: null, ssh: false });
    expect(packTabOf('#pack/skills')).toEqual({ tab: 'skills', ssh: false });
    expect(packTabOf('#settings/pack/work')).toEqual({ tab: 'work', ssh: false });
    expect(packTabOf('#settings/hosts/machines')).toEqual({ tab: 'computers', ssh: true });
    expect(packTabOf('#settings/hosts/pack')).toEqual({ tab: 'computers', ssh: false });
    expect(packTabOf('#hosts/machines')).toEqual({ tab: 'computers', ssh: true });
    expect(packTabOf('#ssh')).toEqual({ tab: 'computers', ssh: true });
    expect(packTabOf('#settings/hosts/computers')).toEqual({ tab: 'computers', ssh: false });
    expect(packTabOf('#settings/appearance')).toBeNull();
    expect(packTabOf('#packs')).toBeNull();
  });
});
