/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import Character from './Character.svelte';
import { createClock, packClock, watchVisibility } from './clock';
import { BUILTIN_PACKS, DEFAULT_PACK, PIXEL_PACK, readCharacterPack } from './pack-reader';
import { buildShapes, HOME_SHAPES, SEGMENTS, type ShapeKey } from './shapes';
import { ALERT_STATES, ALL_STATES, animationOf, EVENT_STATES, heldShape, planMorph, resolveState, STATES, STATUS_STATES } from './states';
import { contrastIndex, MOCKUP_TURN_SECONDS, RIBBON_SLOTS, ribbonsFor, seriesVar, SERIES_COUNT } from './look';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../../../../../..');
const css = fs.readFileSync(path.join(here, 'characters.css'), 'utf8');
const rules = css.replace(/\/\*[\s\S]*?\*\//g, '');

describe('every status and Swarm event maps to exactly one animation', () => {
  test('the vocabulary is the eight status states, asleep, the startup gate, the Swarm events and the alert ladder', () => {
    expect(STATUS_STATES).toEqual(['working', 'working_subagent', 'question', 'notice', 'finished_unread', 'idle', 'dead', 'unknown']);
    expect(new Set([...STATUS_STATES, ...EVENT_STATES, ...ALERT_STATES]).size).toBe(20);
    expect([...ALL_STATES].sort()).toEqual(Object.keys(STATES).sort());
    for (const s of ['asleep', 'startup_gate', 'question_waiting', 'done', 'talking', 'escalating', 'learning', 'promoted']) {
      expect(EVENT_STATES).toContain(s);
    }
  });

  test('each state names one animation and no two states share one', () => {
    const names = ALL_STATES.map((s) => animationOf(s));
    for (const n of names) expect(n).toMatch(/^[a-z][a-z-]*$/);
    expect(new Set(names).size).toBe(ALL_STATES.length);
  });

  test('the stylesheet has a rule keyed on each state (idle is the clock alone) and the clock owns idle', () => {
    for (const s of ALL_STATES) {
      if (s === 'idle') continue;
      expect(rules, s).toContain(`[data-state="${s}"]`);
    }
    expect(rules).not.toContain('[data-state="idle"]');
    expect(STATES.idle.quirk).toBe(true);
    expect(STATES.idle.kind).toBe('rest');
  });

  test('a value that is no state draws as unknown, never idle, and prototype names are not states', () => {
    for (const bad of [null, undefined, '', 'typing', 'constructor', '__proto__', 'toString', 'IDLE']) expect(resolveState(bad)).toBe('unknown');
    for (const s of STATUS_STATES) expect(resolveState(s)).toBe(s);
  });

  test('the alert rungs are four distinct spike layers, ROUTINE to FLASH', () => {
    expect(ALERT_STATES.map((s) => STATES[s].cor)).toEqual(['routine', 'priority', 'immediate', 'flash']);
  });

  test('only transform and opacity animate (plus the individual translate, scale and rotate), and every keyframe set is used', () => {
    const sets = [...rules.matchAll(/@keyframes ([\w-]+)\{([\s\S]*?)\}\s*(?=\.|@|:|$)/g)];
    expect(sets.length).toBeGreaterThan(30);
    const allowed = new Set(['transform', 'opacity', 'scale', 'rotate', 'translate']);
    for (const m of sets) {
      const props = [...m[2]!.matchAll(/([a-z-]+)\s*:/g)].map((x) => x[1]!);
      for (const p of props) expect(allowed.has(p), `${m[1]} animates ${p}`).toBe(true);
      expect(rules.split(`animation:${m[1]} `).length + rules.split(`,${m[1]} `).length + rules.split(`animation-name:${m[1]}}`).length, m[1]).toBeGreaterThan(3);
    }
  });
});

describe('the drop animations replay every 3 s while the state lasts', () => {
  test('escalating and learning loop a 3 s period (half the old 6 s replay), each drop keeping its 1.6 s and 1.8 s shape, with a rest after', () => {
    for (const [name, drop] of [['up', 1.6], ['launch', 1.6], ['down', 1.8], ['gulp', 1.8], ['tilt', 1.8], ['blinkin', 1.8]] as const) {
      expect(css).toMatch(new RegExp(`animation:pk-k-${name} 3s [^;}]* infinite`));
      const kf = css.match(new RegExp(`@keyframes pk-k-${name}\\{(.*)\\}\n`))![1]!;
      const stops = [...kf.matchAll(/(?:^|\})([0-9.%,]+)\{/g)].flatMap((m) => m[1]!.split(',').map((p) => parseFloat(p)));
      const lastMotion = Math.max(...stops.filter((p) => p < 100));
      expect(lastMotion).toBeLessThanOrEqual(((drop / 3) * 100) + 0.01);
    }
  });
});

describe('the body path family', () => {
  const keys: ShapeKey[] = ['sq', 'hex', 'tri', 'tear', 'dot', 'grave', 'qmark'];
  for (const pixel of [false, true]) {
    test(`every shape is M, ${SEGMENTS} cubics and Z with the same structure (${pixel ? 'pixel' : 'default'} pack)`, () => {
      const shapes = buildShapes(pixel);
      for (const k of keys) {
        expect(shapes.d[k].match(/C/g)?.length, k).toBe(SEGMENTS);
        expect(shapes.d[k].match(/M/g)?.length, k).toBe(1);
        expect(shapes.d[k].endsWith('Z')).toBe(true);
        expect(shapes.d[k]).not.toContain('NaN');
      }
      for (const c of Object.values(shapes.corona)) {
        expect(c.length).toBeGreaterThan(100);
        expect(c).not.toContain('NaN');
      }
    });
  }

  test('a state with its own morph starts from the held shape; one without returns to its own in 0.4 s', () => {
    expect(planMorph('dead', null)!.keys).toEqual(['sq', 'grave']);
    expect(planMorph('working_subagent', 'grave')!.keys[0]).toBe('grave');
    expect(planMorph('idle', 'grave')).toEqual({ keys: ['grave', 'sq'], keyTimes: [0, 1], dur: 0.4, spline: '.45 0 .25 1' });
    expect(planMorph('idle', null)).toBeNull();
    expect(planMorph('notice', 'sq')).toBeNull();
    expect(heldShape('startup_gate')).toBe('dot');
  });
});

describe('a hidden tab freezes it', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    document.documentElement.removeAttribute('data-paused');
  });

  function square(state: string, still = false): { el: HTMLElement; pause: ReturnType<typeof vi.fn>; resume: ReturnType<typeof vi.fn> } {
    const el = document.createElement('div');
    el.dataset.state = state;
    if (still) el.setAttribute('data-still', '');
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'pk-bd');
    const pause = vi.fn();
    const resume = vi.fn();
    (svg as unknown as { pauseAnimations: () => void }).pauseAnimations = pause;
    (svg as unknown as { unpauseAnimations: () => void }).unpauseAnimations = resume;
    el.append(svg);
    document.body.append(el);
    return { el, pause, resume };
  }

  test('the stylesheet pauses with animation-play-state and never uses animation none outside reduced motion', () => {
    expect(rules).toContain(':root[data-paused] .pk-sq,:root[data-paused] .pk-sq *{animation-play-state:paused!important}');
    const nones = rules.split('\n').filter((l) => /animation:\s*none/.test(l));
    expect(nones).toHaveLength(1);
    expect(nones[0]).toContain('data-still');
  });

  test('the clock writes the eyes while running, and stops dead when paused: no tick, no timer, SMIL paused', () => {
    const clock = createClock(() => 0.5);
    const { el, pause, resume } = square('idle');
    clock.register(el, () => 'idle');
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(3000);
    expect(el.style.getPropertyValue('--gx')).not.toBe('');
    clock.setPaused(true);
    expect(document.documentElement.hasAttribute('data-paused')).toBe(true);
    expect(pause).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    const frozen = el.getAttribute('style');
    vi.advanceTimersByTime(30000);
    expect(el.getAttribute('style')).toBe(frozen);
    clock.setPaused(false);
    expect(resume).toHaveBeenCalledTimes(1);
    expect(document.documentElement.hasAttribute('data-paused')).toBe(false);
    expect(vi.getTimerCount()).toBe(1);
  });

  test('the clock owns no timer while nothing is registered', () => {
    const clock = createClock();
    const { el } = square('idle');
    const off = clock.register(el, () => 'idle');
    expect(vi.getTimerCount()).toBe(1);
    off();
    expect(vi.getTimerCount()).toBe(0);
  });

  test('the page going hidden pauses the shared clock, and coming back resumes it', () => {
    const { el } = square('idle');
    const off = packClock.register(el, () => 'idle');
    watchVisibility();
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(packClock.isPaused()).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(packClock.isPaused()).toBe(false);
    expect(vi.getTimerCount()).toBe(1);
    off();
  });
});

describe('reduced motion freezes it', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });

  test('the clock skips a still character: no gaze, no blink, no quirk', () => {
    vi.useFakeTimers();
    const clock = createClock(() => 0.5);
    const el = document.createElement('div');
    el.setAttribute('data-still', '');
    clock.register(el, () => 'idle');
    vi.advanceTimersByTime(60000);
    expect(el.getAttribute('style')).toBeNull();
  });

  test('a still Character draws the still shape directly: no SMIL, the "?" for a question, no animation', () => {
    const target = document.createElement('div');
    document.body.append(target);
    const app = mount(Character, { target, props: { state: 'question', size: 40, still: true } });
    flushSync();
    const sq = target.querySelector('.pk-sq')!;
    expect(sq.getAttribute('data-state')).toBe('question');
    expect(sq.hasAttribute('data-still')).toBe(true);
    const body = target.querySelector('path.pk-shp')!;
    expect(body.querySelector('animate')).toBeNull();
    expect(body.getAttribute('d')).toBe(buildShapes(false).d.qmark);
    unmount(app);
  });

  test('a moving Character gets one SMIL morph on its body and one data-state', () => {
    const target = document.createElement('div');
    document.body.append(target);
    const app = mount(Character, { target, props: { state: 'working_subagent', size: 40, still: false, seed: 'Loki', subs: ['a', 'b'] } });
    flushSync();
    expect(target.querySelectorAll('[data-state]')).toHaveLength(1);
    expect(target.querySelectorAll('path.pk-shp animate')).toHaveLength(1);
    expect(target.querySelectorAll('.pk-fxb .pk-orb')).toHaveLength(2);
    expect(target.querySelector('.pk-sq')!.getAttribute('aria-label')).toContain('subagents');
    unmount(app);
  });

  test('prefers-reduced-motion makes a Character still by itself', async () => {
    vi.resetModules();
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), addEventListener: () => undefined, removeEventListener: () => undefined }));
    const { reducedMotion } = await import('./reduced-motion.svelte');
    expect(reducedMotion()).toBe(true);
  });

  test('a Character that is not told to be still reads the media query without throwing (state_unsafe_mutation), and moves when motion is allowed', async () => {
    vi.resetModules();
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
    const sv = await import('svelte');
    const { default: Fresh } = await import('./Character.svelte');
    const target = document.createElement('div');
    document.body.append(target);
    const app = sv.mount(Fresh, { target, props: { state: 'notice', size: 28 } });
    sv.flushSync();
    expect(target.querySelector('.pk-sq')!.hasAttribute('data-still')).toBe(false);
    sv.unmount(app);
  });

  test('no count, dot or glyph is pinned on a square: a state with no tell draws no badge and no glow', () => {
    const target = document.createElement('div');
    document.body.append(target);
    const app = mount(Character, { target, props: { state: 'alert_flash', size: 64, still: true } });
    flushSync();
    expect(target.querySelector('.pk-sq')!.textContent!.trim()).toBe('');
    expect(target.querySelector('.pk-bg, .pk-gw')).toBeNull();
    unmount(app);
  });
});

function ruleOf(sel: string): string {
  const m = rules.split('\n').find((l) => l.startsWith(sel));
  expect(m, sel).toBeDefined();
  return m!;
}


describe('CHARS2: the mockup is back, with the owner changes (docs/swarm.md 13)', () => {
  function draw(props: Record<string, unknown>): { root: Element; target: HTMLElement; off: () => void } {
    const target = document.createElement('div');
    document.body.append(target);
    const app = mount(Character, { target, props: { size: 40, still: false, ...props } as never });
    flushSync();
    return { root: target.querySelector('.pk-sq')!, target, off: () => unmount(app) };
  }

  test('question morphs to the "?" in the mockup timing, and its still pose is the "?"', () => {
    expect(STATES.question.morph).toEqual({ keys: ['sq', 'qmark', 'qmark'], keyTimes: [0, 0.16, 1], dur: 2.2 });
    expect(STATES.question.rest).toBe('qmark');
    expect(STATES.working_subagent.morph!.keys).toEqual(['sq', 'hex', 'tri', 'sq']);
  });

  test('dead ends on the gravestone with its engraving and ground line, drawn in a neutral token, eyes gone', () => {
    expect(heldShape('dead')).toBe('grave');
    expect(planMorph('dead', null)!.keys).toEqual(['sq', 'grave']);
    expect(ruleOf('.pk-sq[data-state="dead"] .pk-shp')).toContain('var(--oc-text-dim)');
    expect(ruleOf('.pk-sq[data-state="dead"] .pk-ex')).toContain('opacity:0');
    const a = draw({ state: 'dead', still: true });
    expect(a.root.querySelector('path.pk-rip')!.getAttribute('d')).toContain('M');
    expect(a.root.querySelector('path.pk-gl')).not.toBeNull();
    a.off();
    const b = draw({ state: 'idle' });
    expect(b.root.querySelector('.pk-rip, .pk-gl')).toBeNull();
    b.off();
  });

  test('priority is the mockup spiky square with no glyph; immediate and flash are a literal copy of the mockup', () => {
    const cor = buildShapes(false).corona;
    const pointsOf = (d: string): number => (d.match(/[ML]/g) ?? []).length;
    expect(pointsOf(cor.priority)).toBe(12 * 21);
    expect(pointsOf(cor.immediate)).toBe(12 * 3);
    expect(pointsOf(cor.flash)).toBe(12 * 6);
    expect(STATES.alert_priority.morph).toBeUndefined();
    expect(STATES.alert_priority.still).toBeUndefined();
    expect(planMorph('alert_priority', null)).toBeNull();
    expect(ruleOf('.pk-sq[data-state="alert_priority"]:not([data-still]) .pk-cor')).toContain('pk-k-pulse');
    expect(css).not.toContain('.pk-sq[data-state="alert_priority"]:not([data-still]) .pk-mv');
    expect(css).not.toContain('.pk-sq[data-state="alert_priority"]:not([data-still]) .pk-cr');
    expect(css).not.toMatch(/\.pk-sq\[data-state="alert_priority"\][^{]*\.pk-ex/);
    expect(css).not.toMatch(/data-still\]\[data-state="alert_priority"\][^{]*\.pk-cor|alert_priority"\]\[data-still/);
    const p = draw({ state: 'alert_priority', still: true });
    expect(p.root.querySelector('use')!.getAttribute('href')).toContain('cor-priority');
    expect(p.root.querySelector('path.pk-shp')!.getAttribute('d')).toBe(buildShapes(false).d.sq);
    expect(p.root.querySelector('animate')).toBeNull();
    p.off();
    for (const s of ['alert_immediate', 'alert_flash'] as const) {
      expect(STATES[s].morph).toBeUndefined();
      expect(STATES[s].still).toBeUndefined();
      expect(planMorph(s, null)).toBeNull();
      expect(ruleOf(`.pk-sq[data-state="${s}"] .pk-ex`)).not.toContain('opacity');
      const live = draw({ state: s });
      expect(live.root.querySelector('animate')).toBeNull();
      expect(live.root.querySelector('use')!.getAttribute('href')).toContain(`cor-${STATES[s].cor}`);
      live.off();
    }
    expect(ruleOf('.pk-sq[data-state="alert_immediate"] .pk-ex')).toContain('scale(1.2)');
    expect(ruleOf('.pk-sq[data-state="alert_flash"] .pk-ex')).toContain('scale(1.36)');
    expect(ruleOf('.pk-sq[data-state="alert_immediate"]:not([data-still]) .pk-cor')).toContain('pk-k-snap .35s cubic-bezier(.2,.9,.3,1.4)');
    expect(ruleOf('.pk-sq[data-state="alert_immediate"]:not([data-still]) .pk-mv')).toContain('pk-k-shake 1.8s linear .35s infinite');
    expect(css).toContain('@keyframes pk-k-shake{0%{transform:none}4%{transform:translateX(-.05em) rotate(-5deg)}');
    expect(css).toContain('24%{transform:translateX(.02em) rotate(1.5deg)}30%,100%{transform:none}}');
    expect(ruleOf('.pk-sq[data-state="alert_flash"]:not([data-still]) .pk-mv')).toContain('pk-k-freak .36s steps(1,end) infinite');
    expect(ruleOf('.pk-sq[data-state="alert_flash"]:not([data-still]) .pk-cor')).toContain('pk-k-flare .5s ease-in-out infinite alternate');
    expect(css).not.toMatch(/pk-k-(alcor|aleyes)/);
    expect(Object.keys(buildShapes(false).d).sort()).toEqual([...new Set(['dot', 'grave', 'qmark', 'tear', ...Object.values(HOME_SHAPES)])].sort());
    expect(planMorph('alert_routine', null)).toBeNull();
  });

  test('working turns its ribbon in 0.6 of the mockup time, and the swoosh is wider', () => {
    RIBBON_SLOTS.forEach((s, i) => expect(s.d).toBeCloseTo(MOCKUP_TURN_SECONDS[i]! * 0.6, 3));
    expect(MOCKUP_TURN_SECONDS).toEqual([2.6, 3.3, 4.1]);
    expect(ribbonsFor('working', 1)[0]!.slot.d).toBeCloseTo(1.56, 3);
    const rib = buildShapes(false).ribbon;
    expect(rib.length).toBeGreaterThan(200);
  });

  test('a ribbon is never the body color, for any of the 8 series, working or with subagents', () => {
    for (let n = 1; n <= SERIES_COUNT; n++) {
      expect(contrastIndex(n)).not.toBe(n);
      expect(ribbonsFor('working', n)[0]!.color).not.toBe(seriesVar(n));
      for (const r of ribbonsFor('working_subagent', n, ['a', 'b', 'c', 'Loki', 'x'])) expect(r.color).not.toBe(seriesVar(n));
    }
  });

  test('no badge element renders for any state, and the only backdrop is the finished_unread glow in a contrast token', () => {
    for (const s of ALL_STATES) {
      const a = draw({ state: s, still: true, seed: 'Loki', tell: 'question' });
      expect(a.root.querySelector('.pk-bg'), s).toBeNull();
      expect(a.root.hasAttribute('data-tell')).toBe(false);
      expect(a.root.querySelector('.pk-gw') !== null, s).toBe(s === 'finished_unread');
      a.off();
    }
    expect(ruleOf('.pk-gw{')).toContain('var(--gc)');
    expect(ruleOf('.pk-gw{')).not.toContain('var(--c)');
    const glow = ruleOf('.pk-gw{');
    expect(glow).toContain('inset:0');
    expect(glow).toContain('border-radius:.22em');
    expect(glow).toMatch(/box-shadow:0 0 [\d.]+em [\d.]+em /);
    expect(glow).not.toMatch(/radial|filter|inset:-/);
    expect(ruleOf('.pk-sq[data-pack="pixel"] .pk-gw{')).toMatch(/box-shadow:0 0 0 [\d.]+em/);
    for (let n = 1; n <= SERIES_COUNT; n++) {
      const a = draw({ state: 'finished_unread', colorIndex: n });
      const st = (a.root as HTMLElement).getAttribute('style')!;
      expect(st).toContain(`--c: ${seriesVar(n)}`);
      expect(st).toContain(`--gc: ${seriesVar(contrastIndex(n))}`);
      expect(contrastIndex(n)).not.toBe(n);
      a.off();
    }
  });

  test('nothing the mockup lacks is drawn: no z marks, no rotating ring, no doubled beats', () => {
    expect(rules).not.toContain('pk-z');
    expect(rules).not.toContain('pk-k-turn');
    expect(rules).not.toMatch(/animation:[^;}]* 2 both/);
    const a = draw({ state: 'asleep' });
    expect(a.root.querySelector('.pk-z')).toBeNull();
    a.off();
    const w = draw({ state: 'working' });
    expect(w.root.querySelectorAll('.pk-dt')).toHaveLength(3);
    w.off();
  });
});

describe('theme character packs: the tolerant reader (pick V)', () => {
  test('a missing or malformed block is the default pack', () => {
    for (const block of [undefined, null, 'pixel', 5, [], {}, { pack: 5 }, { pack: 'nope' }, { pack: 'constructor' }, { pack: '__proto__' }]) {
      expect(readCharacterPack(block)).toBe(DEFAULT_PACK);
    }
  });

  test('a named pack is used, and the owner override wins; an unknown override is ignored', () => {
    expect(readCharacterPack({ pack: 'pixel' })).toBe(PIXEL_PACK);
    expect(readCharacterPack({ pack: 'pixel' }, 'default')).toBe(DEFAULT_PACK);
    expect(readCharacterPack(undefined, 'pixel')).toBe(PIXEL_PACK);
    expect(readCharacterPack({ pack: 'pixel' }, 'theme')).toBe(PIXEL_PACK);
    expect(readCharacterPack({ pack: 'pixel' }, null)).toBe(PIXEL_PACK);
    expect(readCharacterPack(undefined, 'toString')).toBe(DEFAULT_PACK);
    expect(Object.keys(BUILTIN_PACKS).sort()).toEqual(['default', 'pixel']);
  });

  test('a theme naming the pixel pack gets it and carnivore the default squares', () => {
    const themes = path.join(repo, 'client/css/themes');
    const gameboy = { characters: { pack: 'pixel' } };
    const carnivore = JSON.parse(fs.readFileSync(path.join(themes, 'carnivore/theme.json'), 'utf8')) as { characters?: unknown };
    expect(readCharacterPack(gameboy.characters)).toBe(PIXEL_PACK);
    expect(readCharacterPack(carnivore.characters)).toBe(DEFAULT_PACK);
  });
});
