import { describe, expect, it } from 'vitest';
import {
  DRAWER_ODD_WIDTH_PX,
  GLANCE_ROW_PADDING_PX,
  LARGE_CAP_PX,
  OFF_SIZES,
  PHONE_VIEWPORT_PX,
  standardSizes,
} from './standard-sizes';
import { SIZE_UNIT_PX, suggestedSizes } from './fits';
import { namedSize } from './named-sizes';
import { CORE_MANIFESTS } from './core-manifests';
import { harnessWidgets } from '../../widget-harness/catalog';

const floor = { minPx: 240, minHeight: 120 };

describe('standardSizes', () => {
  it('draws s at the floor, m at 4 x 4 units, l at the window cap, the phone, then the off sizes', () => {
    const sizes = standardSizes(floor, 'home');
    expect(sizes.map((s) => s.name)).toEqual(['s', 'm', 'l', 'phone', 'odd-wide', 'odd-tall', 'odd-mid']);
    expect(sizes[0]).toMatchObject({ w: 240, h: 120 });
    expect(sizes[1]).toMatchObject({ w: 384, h: 256 });
    expect(sizes[2]).toMatchObject({ w: LARGE_CAP_PX.w, h: LARGE_CAP_PX.h });
    expect(sizes[3]).toMatchObject({ w: PHONE_VIEWPORT_PX - 32, h: null, viewport: PHONE_VIEWPORT_PX });
  });

  it('holds m at or above a large floor', () => {
    const [s, m] = standardSizes({ minPx: 500, minHeight: 300 }, 'home');
    expect(s).toMatchObject({ w: 500, h: 300 });
    expect(m).toMatchObject({ w: 500, h: 300 });
  });

  it('puts every off size above the floor and off the grid-unit steps, so no suggestion lands on it', () => {
    for (const one of [floor, { minPx: 92, minHeight: 56 }, { minPx: 192, minHeight: 128 }]) {
      const off = standardSizes(one, 'home').filter((s) => s.name.startsWith('odd-'));
      expect(off).toHaveLength(Object.keys(OFF_SIZES).length);
      for (const size of off) {
        expect(size.w).toBeGreaterThan(one.minPx);
        expect(size.h!).toBeGreaterThan(one.minHeight);
        expect(size.w % SIZE_UNIT_PX.w === 0 && size.h! % SIZE_UNIT_PX.h === 0).toBe(false);
        expect(size.w).toBeLessThan(size.viewport);
      }
    }
  });

  it('sizes a drawer widget to the drawer widths with the content deciding the height', () => {
    const sizes = standardSizes(floor, 'drawer');
    expect(sizes.map((s) => [s.name, s.w, s.h])).toEqual([
      ['s', 240, null],
      ['m', 320, null],
      ['l', 480, null],
      ['odd-mid', DRAWER_ODD_WIDTH_PX, null],
    ]);
  });

  it('draws exactly the named sizes a widget calls out on the grids, by name, between the phone and the off sizes', () => {
    const sizes = standardSizes(floor, 'home', null, [namedSize('tall'), namedSize('full')]);
    expect(sizes.map((s) => s.name)).toEqual(['s', 'm', 'l', 'phone', 'tall', 'full', 'odd-wide', 'odd-tall', 'odd-mid']);
    expect(sizes[5]).toMatchObject({ w: 12 * SIZE_UNIT_PX.w, h: 5 * SIZE_UNIT_PX.h, declared: true });
    expect(sizes.filter((s) => s.declared).map((s) => s.name)).toEqual(['tall', 'full']);
    expect(standardSizes(floor, 'drawer', null, [namedSize('tall')]).map((s) => s.name)).not.toContain('tall');
  });

  it('the harness iterates every widget at exactly the names it declares, and no grid numbers name a size', () => {
    for (const widget of harnessWidgets()) {
      const manifest = CORE_MANIFESTS[widget.manifest]!;
      const declared = (widget.sizes.home ?? []).filter((s) => s.declared).map((s) => s.name);
      expect(declared, widget.key).toEqual(suggestedSizes(manifest.fits).map((one) => one.name));
      for (const zone of widget.zones) {
        for (const size of widget.sizes[zone] ?? []) expect(size.name, `${widget.key} ${zone}`).not.toMatch(/\d/);
      }
    }
  });

  it('adds a glance size to the drawer only when a glance height is given', () => {
    expect(standardSizes(floor, 'drawer').map((s) => s.name)).not.toContain('glance');
    const withGlance = standardSizes(floor, 'drawer', 36);
    expect(withGlance.at(-1)).toMatchObject({ name: 'glance', h: 36 + GLANCE_ROW_PADDING_PX });
    expect(standardSizes(floor, 'home', 36).map((s) => s.name)).not.toContain('glance');
  });
});
