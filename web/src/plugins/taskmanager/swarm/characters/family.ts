import { contrastIndex, hashSeed, seriesVar, SERIES_COUNT } from './look';
import { BANDS, byRoom, candidates, column, deltaE, lchCss, mudFloor, shadePool, type Ground, type Lch } from './palette';

export const FIRST_HUE = 25;
export const GOLDEN_ANGLE = 137.50776405003785;
export const FAMILY_SPREAD = 10;
export const MIN_SHADE_DISTANCE = 0.04;

export const VIBRANT_MIN_CHROMA = 0.16;
export const VIBRANT_MAX_CHROMA = 0.22;
export const VIBRANT_DARK_L = 0.84;
export const VIBRANT_LIGHT_L = 0.66;
export const VIBRANT_MAX_DL = 0.08;
export const VIBRANT_MIN_L = VIBRANT_LIGHT_L - VIBRANT_MAX_DL;
export const DARK_GROUND_L = VIBRANT_DARK_L;

function yellowLift(h: number): number {
  return Math.round(0.1 * Math.max(0, Math.cos(((h - 100) * Math.PI) / 180)) ** 24 * 1000) / 1000;
}

export function vibrantBaseL(h: number, groundL: number): number {
  const light = Math.min(1, Math.max(0, (groundL - 0.3) * 2));
  return VIBRANT_DARK_L - (VIBRANT_DARK_L - VIBRANT_LIGHT_L - yellowLift(h)) * light;
}

export function vibrantCss(h: number, dl: number, c: number): string {
  const step = Math.round(Math.min(VIBRANT_MAX_DL, Math.max(-VIBRANT_MAX_DL, dl)) * 1000) / 1000;
  const chroma = Math.round(Math.min(VIBRANT_MAX_CHROMA, Math.max(VIBRANT_MIN_CHROMA, c)) * 1000) / 1000;
  const k = Math.round((VIBRANT_DARK_L - VIBRANT_LIGHT_L - yellowLift(wrapHue(h))) * 1000) / 1000;
  const tail = step === 0 ? '' : step > 0 ? ` + ${step}` : ` - ${-step}`;
  return `oklch(from var(--oc-ground-panel) calc(${VIBRANT_DARK_L} - ${k} * clamp(0, (l - 0.3) * 2, 1)${tail}) ${chroma} ${wrapHue(h)})`;
}

export interface Shade {
  dh: number;
  dl: number;
  c: number;
}

export interface Family {
  key: string;
  hue: number;
  shades: readonly Shade[];
}

export interface ColorMember {
  id: number;
  companyId: number | null;
  projectId?: number | null;
  sysop?: boolean;
  late?: boolean;
  chosenSlot?: number | null;
  base?: boolean;
}

export interface AgentColor {
  body: string;
  contrast: string;
  ribbons: readonly string[];
  family: string;
  shade: { hue: number; dl: number; c: number; l?: number } | null;
}

export type FamilyRule = (member: ColorMember, companyHue: (companyId: number) => number) => Family;

export function wrapHue(h: number): number {
  return Math.round((((h % 360) + 360) % 360) * 10) / 10;
}

export function entityIndex(kind: 'sysop' | 'company' | 'project', id = 0): number {
  return kind === 'sysop' ? 0 : kind === 'company' ? id : -id;
}

export function goldenHue(index: number): number {
  return wrapHue(FIRST_HUE + (index - 1) * GOLDEN_ANGLE);
}

export function companyHue(companyId: number, chosen: number | null = null): number {
  if (typeof chosen === 'number' && Number.isFinite(chosen)) return wrapHue(chosen);
  return goldenHue(entityIndex('company', companyId));
}

export function projectHue(projectId: number): number {
  return goldenHue(entityIndex('project', projectId));
}

export const SYSOP_HUE = 250;

export interface Placement extends Lch {
  hue: number;
  ground: Ground;
}

export type Wheel = ReadonlyMap<string, Placement>;

export function hueArc(a: number, b: number): number {
  const d = Math.abs(wrapHue(a) - wrapHue(b));
  return Math.min(d, 360 - d);
}

const placement = (p: Lch, ground: Ground): Placement => ({ l: p.l, c: p.c, h: p.h, hue: p.h, ground });

function pickFamily(pool: readonly Lch[], taken: readonly Lch[], ground: Ground): Placement | null {
  const ranked = byRoom(pool, taken);
  const roomy = ranked.find((p) => familyShades(placement(p, ground)).length >= MAX_SHADES) ?? ranked[0];
  return roomy ? placement(roomy, ground) : null;
}

function chosenColumn(hue: number, ground: Ground): readonly Lch[] {
  const own = column(wrapHue(hue), ground);
  if (own.length) return own;
  const pool = candidates(ground);
  const near = Math.min(...pool.map((p) => hueArc(p.h, hue)));
  return pool.filter((p) => hueArc(p.h, hue) === near);
}

const wheels = new Map<string, Wheel>();

export function placeFamilies(
  companies: readonly { id: number; hue?: number | null }[],
  projectIds: readonly number[],
  ground: Ground = 'dark',
): Wheel {
  const memo = `${ground}|${companies.map((c) => `${c.id}:${c.hue ?? ''}`).join(',')}|${projectIds.join(',')}`;
  const hit = wheels.get(memo);
  if (hit) return hit;
  const out = new Map<string, Placement>();
  const put = (key: string, p: Placement | null): void => {
    if (p) out.set(key, p);
  };
  const taken = (): Placement[] => [...out.values()];
  const blues = [...column(SYSOP_HUE, ground)].sort((a, b) => b.c - a.c || b.l - a.l);
  const roomy = blues.find((p) => familyShades(placement(p, ground)).length >= MAX_SHADES) ?? blues[0];
  put('sysop', roomy ? placement(roomy, ground) : pickFamily(candidates(ground), [], ground));
  const sortedCompanies = [...companies].sort((a, b) => a.id - b.id);
  for (const c of sortedCompanies) {
    if (typeof c.hue === 'number' && Number.isFinite(c.hue)) put(`company:${c.id}`, pickFamily(chosenColumn(c.hue, ground), taken(), ground));
  }
  const next = (): Placement | null => pickFamily(candidates(ground), taken(), ground);
  for (const c of sortedCompanies) if (!out.has(`company:${c.id}`)) put(`company:${c.id}`, next());
  for (const id of new Set(projectIds)) if (!out.has(`project:${id}`)) put(`project:${id}`, next());
  if (wheels.size >= 32) wheels.clear();
  wheels.set(memo, out);
  return out;
}

export function ghostPlacement(wheel: Wheel): Placement {
  const ground = wheel.values().next().value?.ground ?? 'dark';
  return pickFamily(candidates(ground), [...wheel.values()], ground)!;
}

const NO_WHEEL: Wheel = new Map();

export function okDistance(a: { hue: number; dl: number; c: number }, b: { hue: number; dl: number; c: number }, baseL = DARK_GROUND_L): number {
  const r = Math.PI / 180;
  const da = a.c * Math.cos(a.hue * r) - b.c * Math.cos(b.hue * r);
  const db = a.c * Math.sin(a.hue * r) - b.c * Math.sin(b.hue * r);
  return Math.hypot(baseL + a.dl - (baseL + b.dl), da, db);
}

function farthest(dhs: readonly number[], dls: readonly number[], cs: readonly number[], count: number): Shade[] {
  const grid: Shade[] = [];
  for (const dh of dhs) for (const dl of dls) for (const c of cs) grid.push({ dh, dl, c });
  const at = (s: Shade) => ({ hue: s.dh, dl: s.dl, c: s.c });
  const mid = cs[Math.floor(cs.length / 2)]!;
  const start = grid.find((s) => s.dh === 0 && s.dl === 0 && s.c === mid) ?? grid[0]!;
  const picked: Shade[] = [start];
  const gap = grid.map((s) => okDistance(at(s), at(start)));
  while (picked.length < Math.min(count, grid.length)) {
    let best = -1;
    for (let i = 0; i < grid.length; i++) if (best < 0 || gap[i]! > gap[best]!) best = i;
    const next = grid[best]!;
    picked.push(next);
    for (let i = 0; i < grid.length; i++) gap[i] = Math.min(gap[i]!, okDistance(at(grid[i]!), at(next)));
  }
  return picked;
}

const BRIGHT_DLS = [-VIBRANT_MAX_DL, -0.04, 0, 0.04, VIBRANT_MAX_DL];
const BRIGHT_CS = [VIBRANT_MIN_CHROMA, 0.19, VIBRANT_MAX_CHROMA];

export const SHADES: readonly Shade[] = farthest([-FAMILY_SPREAD, -FAMILY_SPREAD / 2, 0, FAMILY_SPREAD / 2, FAMILY_SPREAD], BRIGHT_DLS, BRIGHT_CS, 20);

export const MAX_SHADES = 20;
const SHADE_DL = 0.15;
const SHADE_CHORD = 0.08;
export const SHADE_RADIUS = 0.16;

export function shadeSpread(c: number): number {
  return (360 / Math.PI) * Math.asin(Math.min(1, SHADE_CHORD / (2 * c)));
}
const shadeTables = new Map<string, readonly Lch[]>();

export function familyShades(base: Placement): readonly Lch[] {
  const key = `${base.ground}:${base.l}:${base.c}:${base.h}`;
  const hit = shadeTables.get(key);
  if (hit) return hit;
  const { maxL } = BANDS[base.ground];
  const floor = Math.max(BANDS[base.ground].minL, mudFloor(base.h));
  const lo = Math.max(floor, Math.min(base.l - SHADE_DL, maxL - 2 * SHADE_DL));
  const spread = shadeSpread(base.c);
  const near = shadePool(base.ground).filter((p) => p.l >= lo - 1e-9 && p.l <= lo + 2 * SHADE_DL + 1e-9 && hueArc(p.h, base.h) <= spread && deltaE(p, base) <= SHADE_RADIUS);
  const picked: Lch[] = [{ l: base.l, c: base.c, h: base.h }];
  const gap = near.map((p) => deltaE(p, picked[0]!));
  while (picked.length < MAX_SHADES) {
    let best = -1;
    for (let i = 0; i < near.length; i++) if (best < 0 || gap[i]! > gap[best]! + 1e-12) best = i;
    if (best < 0 || gap[best]! < MIN_SHADE_DISTANCE - 1e-9) break;
    const next = near[best]!;
    picked.push(next);
    for (let i = 0; i < near.length; i++) gap[i] = Math.min(gap[i]!, deltaE(near[i]!, next));
  }
  shadeTables.set(key, picked);
  return picked;
}

export const SYSOP: Family = { key: 'sysop', hue: SYSOP_HUE, shades: SHADES };

export const byProject: FamilyRule = (member, hueOf) => {
  if (member.sysop) return SYSOP;
  if (member.projectId != null) return { key: `project:${member.projectId}`, hue: projectHue(member.projectId), shades: SHADES };
  if (member.companyId != null) return { key: `company:${member.companyId}`, hue: hueOf(member.companyId), shades: SHADES };
  return SYSOP;
};

export const byRandom: FamilyRule = (member) => {
  const n = Math.abs(Math.round(member.id));
  return {
    key: `random:${member.id}`,
    hue: wrapHue(member.id * GOLDEN_ANGLE),
    shades: [{ dh: 0, dl: BRIGHT_DLS[n % BRIGHT_DLS.length]!, c: BRIGHT_CS[Math.floor(n / BRIGHT_DLS.length) % BRIGHT_CS.length]! }],
  };
};

function contrastsOf(h: number): { contrast: string; ribbons: string[] } {
  const at = (d: number) => vibrantCss(h + 180 + d, 0, 0.19);
  return { contrast: at(0), ribbons: [at(0), at(40), at(-40)] };
}

function chosenColor(slot: number): AgentColor {
  const ci = contrastIndex(slot);
  const near = (d: number) => seriesVar(((ci - 1 + d + SERIES_COUNT) % SERIES_COUNT) + 1);
  return { body: seriesVar(slot), contrast: seriesVar(ci), ribbons: [near(0), near(1), near(-1)], family: 'chosen', shade: null };
}

export function assignColors(
  members: readonly ColorMember[],
  wheel: Wheel = NO_WHEEL,
  rule: FamilyRule = byProject,
): Map<number, AgentColor> {
  const hueOf = (id: number) => wheel.get(`company:${id}`)?.hue ?? companyHue(id);
  const held = new Map<string, Set<number>>();
  const out = new Map<number, AgentColor>();
  const ghost = wheel.size ? ghostPlacement(wheel) : undefined;
  const order = [...members].sort((a, b) => Number(!!a.late) - Number(!!b.late) || Number(!a.base) - Number(!b.base) || a.id - b.id);
  for (const m of order) {
    if (out.has(m.id)) continue;
    const slot = m.chosenSlot;
    if (typeof slot === 'number' && slot >= 1 && slot <= SERIES_COUNT) {
      out.set(m.id, chosenColor(Math.round(slot)));
      continue;
    }
    const ruled = rule(m, hueOf);
    const placed = wheel.get(ruled.key) ?? (ruled.key.startsWith('project:') ? ghost : undefined);
    const n = placed ? familyShades(placed).length : ruled.shades.length;
    const taken = held.get(ruled.key) ?? new Set<number>();
    held.set(ruled.key, taken);
    const want = m.base ? 0 : hashSeed(m.id) % n;
    let pick = want;
    for (let k = 0; k < n; k++) {
      if (!taken.has((want + k) % n)) {
        pick = (want + k) % n;
        break;
      }
    }
    taken.add(pick);
    if (placed) {
      const s = familyShades(placed)[pick]!;
      const dl = Math.round((s.l - placed.l) * 1000) / 1000;
      out.set(m.id, { body: lchCss(s), ...contrastsOf(placed.hue), family: ruled.key, shade: { hue: s.h, dl, c: s.c, l: s.l } });
      continue;
    }
    const s = ruled.shades[pick]!;
    const hue = wrapHue(ruled.hue + s.dh);
    out.set(m.id, { body: vibrantCss(hue, s.dl, s.c), ...contrastsOf(ruled.hue), family: ruled.key, shade: { hue, dl: s.dl, c: s.c } });
  }
  return out;
}

export function colorOfMember(member: ColorMember, wheel: Wheel = NO_WHEEL, rule: FamilyRule = byProject): AgentColor {
  return assignColors([member], wheel, rule).get(member.id)!;
}
