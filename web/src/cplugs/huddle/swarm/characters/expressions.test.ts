/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { createClock, TICK_MS } from './clock';
import {
  applyExpression, clearExpression, eligible, EXPRESSIONS, EXPR_MAX_MS, EXPR_MIN_MS, nextDelay, pickCharacter, pickExpression,
  SETTLE_MS, type Candidate,
} from './expressions';
import type { CharacterState } from './states';

function seeded(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const cand = (over: Partial<Candidate> = {}): Candidate => ({ state: 'idle', still: false, visible: true, ageMs: SETTLE_MS, ...over });

function rig(states: CharacterState[], r = seeded(7), visible = true) {
  const clock = createClock(r, () => visible);
  const els = states.map((st) => {
    const el = document.createElement('div');
    el.className = 'pk-sq';
    document.body.append(el);
    clock.register(el, () => st);
    return el;
  });
  const run = (ms: number): void => {
    for (let t = 0; t < ms; t += TICK_MS) clock.tick();
  };
  const watch = (ms: number): string[] => {
    const seen: string[] = [];
    for (let t = 0; t < ms; t += TICK_MS) {
      clock.tick();
      const n = els[0]!.getAttribute('data-fx');
      if (n && seen[seen.length - 1] !== n) seen.push(n);
    }
    return seen;
  };
  return { clock, els, run, watch };
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('the catalog', () => {
  test('exactly 50 entries with unique names and pairwise-different eye data', () => {
    expect(EXPRESSIONS).toHaveLength(50);
    expect(new Set(EXPRESSIONS.map((x) => x.name)).size).toBe(50);
    expect(new Set(EXPRESSIONS.map((x) => JSON.stringify([x.l, x.r, x.motion]))).size).toBe(50);
  });
  test('each face lasts 1.2 to 2.5 s and keeps its eyes inside the face', () => {
    for (const x of EXPRESSIONS) {
      expect(x.ms).toBeGreaterThanOrEqual(1200);
      expect(x.ms).toBeLessThanOrEqual(2500);
      for (const e of [x.l, x.r]) {
        expect(Math.abs(e.x)).toBeLessThanOrEqual(0.1);
        expect(Math.abs(e.y)).toBeLessThanOrEqual(0.1);
        expect(e.w).toBeLessThanOrEqual(0.3);
        expect(e.h).toBeLessThanOrEqual(0.4);
      }
    }
  });
  test('apply writes both eyes as custom properties and clear removes every one', () => {
    const el = document.createElement('div');
    applyExpression(el, EXPRESSIONS.find((x) => x.name === 'wink left')!, false);
    expect(Number(el.style.getPropertyValue('--fl-sx'))).toBeCloseTo(1.6, 6);
    expect(el.style.getPropertyValue('--fr-clip')).toBe('none');
    expect(el.getAttribute('data-fm')).toBe('none');
    clearExpression(el);
    expect(el.getAttribute('style') ?? '').toBe('--gx: 0; --gy: 0;');
    expect(el.hasAttribute('data-fm')).toBe(false);
  });
  test('the pixel pack gets blocky shapes and the right eye of a mirrored face is flipped', () => {
    const el = document.createElement('div');
    applyExpression(el, EXPRESSIONS.find((x) => x.name === 'angry')!, true);
    expect(el.style.getPropertyValue('--fl-clip')).toContain('40% 0');
    expect(Number(el.style.getPropertyValue('--fr-sx'))).toBeLessThan(0);
  });
});

describe('the schedule', () => {
  test('the pick interval stays within 120 to 180 s over many draws', () => {
    const r = seeded(1);
    for (let i = 0; i < 2000; i++) {
      const d = nextDelay(r);
      expect(d).toBeGreaterThanOrEqual(EXPR_MIN_MS);
      expect(d).toBeLessThanOrEqual(EXPR_MAX_MS);
    }
  });
  test('only visible, settled, resting, motion-allowed characters are ever picked', () => {
    const states: CharacterState[] = ['idle', 'finished_unread', 'dead', 'asleep', 'working', 'working_subagent', 'question', 'startup_gate', 'alert_routine', 'alert_priority', 'alert_immediate', 'alert_flash', 'unknown', 'done'];
    for (const st of states) expect(eligible(cand({ state: st }))).toBe(st === 'idle' || st === 'finished_unread');
    expect(eligible(cand({ visible: false }))).toBe(false);
    expect(eligible(cand({ still: true }))).toBe(false);
    expect(eligible(cand({ ageMs: SETTLE_MS - 1 }))).toBe(false);
    const r = seeded(3);
    const pool = [cand({ state: 'dead' }), cand(), cand({ visible: false }), cand({ state: 'finished_unread' }), cand({ still: true })];
    for (let i = 0; i < 500; i++) expect([1, 3]).toContain(pickCharacter(pool, r));
    expect(pickCharacter([cand({ state: 'working' })], r)).toBe(-1);
  });
  test('no expression repeats back to back', () => {
    const r = seeded(5);
    let prev: string | null = null;
    for (let i = 0; i < 3000; i++) {
      const x = pickExpression(prev, r);
      expect(x.name).not.toBe(prev);
      prev = x.name;
    }
  });
});

describe('the shared clock', () => {
  test('plays one face on a resting square within 180 s, ends it after its duration and returns the eyes to normal', () => {
    const { els, run, watch } = rig(['idle']);
    expect(watch(EXPR_MAX_MS + 3 * TICK_MS)).toHaveLength(1);
    run(2600);
    expect(els[0]!.hasAttribute('data-fx')).toBe(false);
    expect(els[0]!.style.getPropertyValue('--fl-sx')).toBe('');
  });
  test('never plays on a non-resting character', () => {
    const { els, run } = rig(['dead', 'asleep', 'working', 'question', 'alert_flash']);
    let seen = false;
    for (let i = 0; i < 6; i++) {
      run(EXPR_MAX_MS);
      seen ||= els.some((e) => e.hasAttribute('data-fx'));
    }
    expect(seen).toBe(false);
  });
  test('an off-screen square gets none', () => {
    const { els, run } = rig(['idle'], seeded(2), false);
    for (let i = 0; i < 4; i++) run(EXPR_MAX_MS);
    expect(els[0]!.hasAttribute('data-fx')).toBe(false);
  });
  test('a hidden tab (paused clock) suppresses it, and reduced motion gets none at all', () => {
    const paused = rig(['idle']);
    paused.clock.setPaused(true);
    paused.run(EXPR_MAX_MS * 3);
    expect(paused.els[0]!.hasAttribute('data-fx')).toBe(false);
    document.body.innerHTML = '';
    const still = rig(['idle']);
    still.els[0]!.setAttribute('data-still', '');
    still.run(EXPR_MAX_MS * 3);
    still.clock.play(still.els[0]!, EXPRESSIONS[0]!);
    expect(still.els[0]!.hasAttribute('data-fx')).toBe(false);
  });
  test('across many plays the same face never comes twice in a row', () => {
    const { watch } = rig(['idle'], seeded(11));
    const seen = watch(EXPR_MAX_MS * 40);
    expect(seen.length).toBeGreaterThan(30);
    for (let i = 1; i < seen.length; i++) expect(seen[i]).not.toBe(seen[i - 1]);
  });
});
