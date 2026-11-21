import { describe, expect, it } from 'vitest';
import type { BoardSave } from './board-model';
import { draftOf, MAX_PAYLOAD_BYTES, samePayload, stableJson, stepSave, validatePayload } from './payload-model';

const save = (n: number, payload: Record<string, unknown> = { n }): BoardSave => ({ n, at: `2026-10-13T15:0${n}:00Z`, payload });

describe('validatePayload', () => {
  it('takes a plain JSON object and returns a clean copy', () => {
    const input = { items: { milk: true }, list: [1, 'two', null] };
    const out = validatePayload(input);
    expect(out).toEqual(input);
    expect(out).not.toBe(input);
  });
  it('takes the empty object', () => expect(validatePayload({})).toEqual({}));
  it('refuses a list, a scalar, null and nothing', () => {
    for (const bad of [[1], 'x', 3, null, undefined, true]) expect(validatePayload(bad)).toBeNull();
  });
  it('refuses a payload over the byte cap, counting UTF-8 bytes not characters', () => {
    expect(validatePayload({ pad: 'x'.repeat(MAX_PAYLOAD_BYTES - 20) })).not.toBeNull();
    expect(validatePayload({ pad: 'x'.repeat(MAX_PAYLOAD_BYTES) })).toBeNull();
    expect(validatePayload({ pad: 'é'.repeat(MAX_PAYLOAD_BYTES / 2 - 2) })).toBeNull();
  });
  it('refuses a cycle and a payload nested past 32 levels', () => {
    const cycle: Record<string, unknown> = {};
    cycle.self = cycle;
    expect(validatePayload(cycle)).toBeNull();
    let deep: Record<string, unknown> = {};
    const top = deep;
    for (let i = 0; i < 40; i += 1) deep = (deep.n = {});
    expect(validatePayload(top)).toBeNull();
  });
});

describe('comparing payloads', () => {
  it('ignores key order', () => {
    expect(samePayload({ a: 1, b: { c: 2, d: [1, { e: 1, f: 2 }] } }, { b: { d: [1, { f: 2, e: 1 }], c: 2 }, a: 1 })).toBe(true);
    expect(samePayload({ a: 1 }, { a: 2 })).toBe(false);
    expect(samePayload({ a: 1 }, null)).toBe(false);
    expect(stableJson({ b: 1, a: [2] })).toBe('{"a":[2],"b":1}');
  });
});

describe('stepSave', () => {
  const saves = [save(1), save(2), save(3)];
  it('steps back from the newest, one at a time, and stops at the first', () => {
    expect(stepSave(saves, null, -1)).toBe(3);
    expect(stepSave(saves, 3, -1)).toBe(2);
    expect(stepSave(saves, 1, -1)).toBe(1);
  });
  it('steps forward and stops at the newest', () => {
    expect(stepSave(saves, 1, 1)).toBe(2);
    expect(stepSave(saves, 3, 1)).toBeNull();
  });
  it('has nothing to step through without saves', () => expect(stepSave([], null, -1)).toBeNull());
});

describe('draftOf', () => {
  it('is the revision draft, or null', () => {
    const base = { id: 'r1', n: 1, created_at: '', summary: '', answers_round: null, viewport: 400, views: [], prompts: [], anchors: [] };
    expect(draftOf({ ...base, draft: { at: 't', payload: { a: 1 } } })).toEqual({ at: 't', payload: { a: 1 } });
    expect(draftOf(base)).toBeNull();
    expect(draftOf(null)).toBeNull();
  });
});
