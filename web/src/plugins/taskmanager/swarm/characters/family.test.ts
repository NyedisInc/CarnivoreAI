import { describe, expect, test } from 'vitest';
import {
  assignColors, familyShades, ghostPlacement, MAX_SHADES, MIN_SHADE_DISTANCE, placeFamilies, SHADE_RADIUS, shadeSpread, SYSOP_HUE,
  VIBRANT_MIN_CHROMA, VIBRANT_MIN_L, vibrantCss, type AgentColor, type ColorMember, type Wheel,
} from './family';
import { BANDS, deltaE, fromLinearSrgb, inGamut, linearSrgb, mudFloor, oklab, PALETTE_MIN_CHROMA, type Ground, type Lch } from './palette';

const MIN_FAMILY_DISTANCE = 0.1;

const arc = (a: number, b: number) => Math.min(Math.abs(a - b), 360 - Math.abs(a - b));

const concrete = (css: string): Lch | null => {
  const m = css.match(/^oklch\(([\d.]+) ([\d.]+) ([\d.]+)\)$/);
  return m ? { l: Number(m[1]), c: Number(m[2]), h: Number(m[3]) } : null;
};

const relative = (css: string, groundL: number) => {
  const m = css.match(/^oklch\(from var\(--oc-ground-panel\) calc\(([\d.]+) - ([\d.]+) \* clamp\(0, \(l - ([\d.]+)\) \* (\d+), 1\)(?: ([+-]) ([\d.]+))?\) ([\d.]+) ([\d.]+)\)$/);
  expect(m, css).not.toBeNull();
  const [, base, k, lo, mul, sign, step, c] = m!;
  const light = Math.min(1, Math.max(0, (groundL - Number(lo)) * Number(mul)));
  return { l: Number(base) - Number(k) * light + (sign === '-' ? -1 : 1) * Number(step ?? 0), c: Number(c) };
};

const strings = (book: Map<number, AgentColor>) => [...book.values()].flatMap((c) => [c.body, c.contrast, ...c.ribbons]);

const project = (projectId: number, first: number, n: number, companyId: number | null = null): ColorMember[] =>
  Array.from({ length: n }, (_, i) => ({ id: first + i, companyId, projectId, base: i === 0, late: i >= n - 4 }));

const closest = (named: readonly [string, Lch][]) => {
  let best = { d: Infinity, pair: ['', ''] };
  for (let i = 0; i < named.length; i++) {
    for (let j = 0; j < i; j++) {
      const d = deltaE(named[i]![1], named[j]![1]);
      if (d < best.d) best = { d, pair: [named[i]![0], named[j]![0]] };
    }
  }
  return best;
};

const GROUNDS: readonly Ground[] = ['dark', 'light'];

describe('color families', () => {
  const COMPANIES = [{ id: 1 }, { id: 2 }];
  const PROJECTS = [59, 1, 17, 20, 16, 72, 73, 6, 54];
  const ALL = [...Array.from({ length: 49 }, (_, i) => i + 1).filter((id) => id !== 19), 54, 55, 56, 57, 58, 59, 60, 66, 68, 70, 71, 72, 73];
  const wheels = new Map<Ground, Wheel>(GROUNDS.map((g) => [g, placeFamilies(COMPANIES, PROJECTS, g)]));

  test.each(GROUNDS)('on a %s ground every two top-level families sit at least 0.10 apart in OKLab, the reported trio included', (ground) => {
    const wheel = wheels.get(ground)!;
    expect(wheel.size).toBe(1 + COMPANIES.length + PROJECTS.length);
    const named = [...wheel].map(([k, p]) => [k, p] as [string, Lch]);
    const near = closest(named);
    expect(near.d, `${near.pair.join(' vs ')} on ${ground}`).toBeGreaterThanOrEqual(MIN_FAMILY_DISTANCE);
    const trio = ['project:59', 'project:1', 'project:6'].map((k) => [k, wheel.get(k)!] as [string, Lch]);
    expect(closest(trio).d).toBeGreaterThanOrEqual(MIN_FAMILY_DISTANCE);
    expect(wheel.get('sysop')!.hue).toBe(SYSOP_HUE);
    for (const p of wheel.values()) {
      expect(inGamut(p), JSON.stringify(p)).toBe(true);
      expect(p.l).toBeGreaterThanOrEqual(BANDS[ground].minL);
      expect(p.l).toBeLessThanOrEqual(BANDS[ground].maxL);
      expect(p.c).toBeGreaterThanOrEqual(PALETTE_MIN_CHROMA);
      expect(p.l).toBeGreaterThanOrEqual(mudFloor(p.h));
    }
  });

  test('the old hue-only picker fails the same bar once its colors are rendered (clipped to sRGB)', () => {
    const OLD: [string, number, number][] = [
      ['sysop', 250, 0], ['company:1', 70, 0.06], ['company:2', 160, -0.06], ['project:59', 340, -0.06], ['project:1', 10, 0],
      ['project:17', 40, -0.06], ['project:20', 100, 0], ['project:16', 130, 0.06], ['project:72', 190, 0.06],
      ['project:73', 220, -0.06], ['project:6', 280, 0.06], ['project:54', 310, 0],
    ];
    const rendered = ([name, h, dl]: [string, number, number]): [string, Lch] => {
      const rgb = linearSrgb(oklab({ l: 0.84 + dl, c: 0.19, h })).map((v) => Math.min(1, Math.max(0, v))) as [number, number, number];
      const [l, a, b] = fromLinearSrgb(rgb);
      return [name, { l, c: Math.hypot(a, b), h: (Math.atan2(b, a) * 180) / Math.PI }];
    };
    expect(closest(OLD.map(rendered)).d).toBeLessThan(MIN_FAMILY_DISTANCE);
  });

  test('a project with no agent reserves nothing: it wears the next free color and moves no placed family', () => {
    for (const wheel of wheels.values()) {
      const placed = PROJECTS.map((id, i) => ({ id: 100 + i, companyId: null, projectId: id, base: true }));
      const ghosts = ALL.filter((id) => !PROJECTS.includes(id)).map((id) => ({ id: 1000 + id, companyId: null, projectId: id, late: true }));
      const alone = assignColors(placed, wheel);
      const crowded = assignColors([...placed, ...ghosts], wheel);
      for (const m of placed) expect(crowded.get(m.id)).toEqual(alone.get(m.id));
      const next = ghostPlacement(wheel);
      for (const g of ghosts) expect(arc(crowded.get(g.id)!.shade!.hue, next.hue)).toBeLessThanOrEqual(shadeSpread(next.c));
      const grown = placeFamilies(COMPANIES, [...PROJECTS, 30], next.ground);
      expect(grown.get('project:30')).toEqual(next);
      for (const [key, at] of wheel) expect(grown.get(key)).toEqual(at);
    }
  });

  test('a new project, even one with a lower id, never moves an older color; a chosen company hue is honoured', () => {
    for (const [ground, wheel] of wheels) {
      const grown = placeFamilies(COMPANIES, [...PROJECTS, 3, 2], ground);
      for (const [key, at] of wheel) expect(grown.get(key)).toEqual(at);
      const chosen = placeFamilies([{ id: 1 }, { id: 2, hue: 140 }], [1, 6], ground);
      expect(chosen.get('company:2')!.hue).toBe(140);
      const book = assignColors([{ id: 9, companyId: 2, base: true }, { id: 10, companyId: 1, projectId: 6, base: true }], chosen);
      expect(book.get(9)!.shade!.hue).toBe(140);
      expect(book.get(10)!.shade!.hue).toBe(chosen.get('project:6')!.hue);
      expect(book.get(10)!.shade!.l).toBe(chosen.get('project:6')!.l);
      expect(book.get(10)!.shade!.dl).toBe(0);
    }
  });

  test("a project's agents share its tone: near its color, the project agent on it", () => {
    for (const wheel of wheels.values()) {
      const members = project(16, 10, 12, 2);
      const book = assignColors(members, wheel);
      const base = wheel.get('project:16')!;
      expect(concrete(book.get(10)!.body)).toEqual({ l: base.l, c: base.c, h: base.h });
      for (const m of members) {
        const s = book.get(m.id)!.shade!;
        expect(book.get(m.id)!.family).toBe('project:16');
        expect(arc(s.hue, base.hue)).toBeLessThanOrEqual(shadeSpread(base.c));
        expect(deltaE({ l: s.l!, c: s.c, h: s.hue }, base)).toBeLessThanOrEqual(SHADE_RADIUS);
      }
    }
  });

  test('siblings keep a minimum perceptual distance, all 20 of them, in every live family on both grounds', () => {
    for (const wheel of wheels.values()) {
      for (const base of wheel.values()) expect(familyShades(base)).toHaveLength(MAX_SHADES);
      const members = project(17, 10, 20);
      const book = assignColors(members, wheel);
      const shades = members.map((m) => concrete(book.get(m.id)!.body)!);
      expect(new Set(members.map((m) => book.get(m.id)!.body)).size).toBe(20);
      for (let i = 0; i < shades.length; i++) {
        for (let j = 0; j < i; j++) expect(deltaE(shades[i]!, shades[j]!)).toBeGreaterThanOrEqual(MIN_SHADE_DISTANCE);
      }
    }
  });

  test('the same id gives the same color, whatever the order, and a newcomer never moves an older sibling', () => {
    const wheel = wheels.get('dark')!;
    const members = project(1, 1, 10);
    const one = assignColors(members, wheel);
    const two = assignColors([...members].reverse(), wheel);
    for (const m of members) expect(two.get(m.id)).toEqual(one.get(m.id));
    const grown = assignColors([...members, { id: 50, companyId: null, projectId: 1 }], wheel);
    for (const m of members.filter((x) => !x.late)) expect(grown.get(m.id)!.body).toBe(one.get(m.id)!.body);
  });

  test('dark and light grounds get their own sets: lighter marks on dark, deeper on light', () => {
    const dark = wheels.get('dark')!;
    const light = wheels.get('light')!;
    expect(Math.max(...[...light.values()].map((p) => p.l))).toBeLessThanOrEqual(BANDS.light.maxL);
    expect(Math.max(...[...dark.values()].map((p) => p.l))).toBeGreaterThan(BANDS.light.maxL);
  });

  test("a hand-set color wins, and a company's chosen hue moves only the company's own members", () => {
    const members: ColorMember[] = [
      { id: 1, companyId: 2, chosenSlot: 3 }, { id: 2, companyId: 2, base: true }, { id: 3, companyId: 2, projectId: 4 },
    ];
    const plain = assignColors(members, placeFamilies([{ id: 2 }], [4]));
    const recolored = assignColors(members, placeFamilies([{ id: 2, hue: 300 }], [4]));
    expect(plain.get(1)!.body).toBe('var(--oc-series-3)');
    expect(recolored.get(1)!.body).toBe('var(--oc-series-3)');
    expect(plain.get(1)!.contrast).not.toBe(plain.get(1)!.body);
    expect(recolored.get(2)!.shade!.hue).toBe(300);
    expect(arc(recolored.get(3)!.shade!.hue, 300)).toBeGreaterThanOrEqual(20);
  });

  test("SysOp, and anything with neither a project nor a company, wear SysOp's family; no hex anywhere", () => {
    const book = assignColors([{ id: 1, companyId: null }, { id: 2, companyId: 1, projectId: 9, sysop: true, base: true }, { id: 3, companyId: 1 }], placeFamilies([{ id: 1 }], [9]));
    expect(book.get(2)!.family).toBe('sysop');
    expect(book.get(2)!.shade!.hue).toBe(SYSOP_HUE);
    expect(book.get(1)!.family).toBe('sysop');
    expect(book.get(3)!.family).toBe('company:1');
    for (const c of book.values()) {
      for (const css of [c.body, c.contrast, ...c.ribbons]) expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|rgb/i);
      expect(c.ribbons).not.toContain(c.body);
    }
  });

  test('every emitted color is vibrant: concrete ones in sRGB above the floor, relative ones on a dark, a mid and a light ground', () => {
    const members: ColorMember[] = [
      { id: 1, companyId: null }, { id: 2, companyId: null, sysop: true },
      ...[1, 2, 3, 4].map((co) => ({ id: 10 + co, companyId: co })),
      ...Array.from({ length: 45 }, (_, i) => project(i + 1, (i + 1) * 100, 20, (i % 3) || null)).flat(),
    ];
    const all = GROUNDS.flatMap((g) => strings(assignColors(members, placeFamilies([1, 2, 3, 4].map((id) => ({ id })), Array.from({ length: 45 }, (_, i) => i + 1), g))));
    all.push(vibrantCss(100, -1, 0), vibrantCss(300, 1, 1));
    expect(all.length).toBeGreaterThan(2000);
    let seen = 0;
    for (const css of all) {
      const p = concrete(css);
      if (p) {
        seen++;
        expect(inGamut(p), css).toBe(true);
        expect(p.c, css).toBeGreaterThanOrEqual(PALETTE_MIN_CHROMA);
        expect(p.l, css).toBeGreaterThanOrEqual(Math.max(mudFloor(p.h), BANDS.light.minL));
        continue;
      }
      for (const groundL of [0.1, 0.55, 0.98]) {
        const { l, c } = relative(css, groundL);
        expect(c, css).toBeGreaterThanOrEqual(VIBRANT_MIN_CHROMA);
        expect(l, css).toBeGreaterThanOrEqual(VIBRANT_MIN_L - 1e-9);
        expect(l, css).toBeLessThanOrEqual(0.95);
      }
    }
    expect(seen).toBeGreaterThan(1500);
  });
});
