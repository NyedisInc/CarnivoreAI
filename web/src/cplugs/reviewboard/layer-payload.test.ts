import { describe, expect, it, vi } from 'vitest';
import { fitsLayer, type BoardLayer } from './layer-payload';
import { LAYER_STRING_NAMES, LAYER_STRING_PREFIX, layerStrings } from './layer-strings';
import type { BoardRevision } from './board-model';

vi.mock('./board-api', () => ({ sendRoundKept: vi.fn(), savePayloadDraft: vi.fn(async () => undefined) }));
const { PayloadLoop } = await import('./payload-loop.svelte');

const OPTIONS = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
const LAYER: BoardLayer = {
  kind: 'questions',
  items: [
    { id: 'rail', kind: 'yesno' }, { id: 'dense', kind: 'toggle' }, { id: 'density', kind: 'choice', options: OPTIONS },
    { id: 'panels', kind: 'multi', options: OPTIONS, max: 2 }, { id: 'order', kind: 'rank', options: OPTIONS }, { id: 'name', kind: 'text' },
    { id: 'size', kind: 'number', min: 1, max: 10 }, { id: 'due', kind: 'date', min: '2026-10-01', max: '2026-12-31' },
  ],
};
const GOOD = { layer: 'questions', v: 1, values: { rail: true, dense: false, density: 'a', panels: ['a', 'c'], order: ['c', 'b', 'a'], name: 'n', size: 3, due: '2026-11-02' }, notes: { rail: 'x' } };
const withValue = (id: string, value: unknown) => ({ ...GOOD, values: { [id]: value } });

describe('fitsLayer', () => {
  it('takes a payload that fits, and one with no values at all', () => {
    expect(fitsLayer(LAYER, GOOD)).toBe(true);
    expect(fitsLayer(LAYER, { layer: 'questions', v: 1, values: {} })).toBe(true);
  });

  it.each([
    ['another layer name', { ...GOOD, layer: 'rows' }],
    ['another version', { ...GOOD, v: 2 }],
    ['a stray top-level key', { ...GOOD, picks: {} }],
    ['values that is a list', { ...GOOD, values: [] }],
    ['an unknown item', withValue('ghost', 1)],
    ['a yesno that is a string', withValue('rail', 'yes')],
    ['a choice outside its options', withValue('density', 'z')],
    ['a multi over max', withValue('panels', ['a', 'b', 'c'])],
    ['a multi with a repeat', withValue('panels', ['a', 'a'])],
    ['a rank missing an option', withValue('order', ['a', 'b'])],
    ['a number below min', withValue('size', 0)],
    ['a number that is NaN-like text', withValue('size', '3')],
    ['a date outside its range', withValue('due', '2027-01-01')],
    ['a note on an unknown item', { ...GOOD, notes: { ghost: 'x' } }],
    ['a note that is not text', { ...GOOD, notes: { rail: 5 } }],
  ])('drops %s', (_name, payload) => {
    expect(fitsLayer(LAYER, payload)).toBe(false);
  });

  it('checks a rows layer by the row\'s own choices, else the layer\'s', () => {
    const rows: BoardLayer = { kind: 'rows', pick: 'one', choices: [{ id: 'ok' }], rows: [{ id: 'r1' }, { id: 'r2', choices: [{ id: 'keep' }] }] };
    expect(fitsLayer(rows, { layer: 'rows', v: 1, values: { r1: 'ok', r2: 'keep' } })).toBe(true);
    expect(fitsLayer(rows, { layer: 'rows', v: 1, values: { r2: 'ok' } })).toBe(false);
  });
});

describe('the strings sent to the frame', () => {
  it('has every key in the catalog, so none reaches the frame as its own key', () => {
    const sent = layerStrings();
    expect(Object.keys(sent)).toHaveLength(LAYER_STRING_NAMES.length);
    for (const [key, text] of Object.entries(sent)) expect(text, key).not.toBe(key);
    expect(sent[`${LAYER_STRING_PREFIX}yes`]).toBe('yes');
  });
});

describe('the loop drops a misfit before it can be autosaved', () => {
  it('keeps the payload that fits and refuses the one that does not', () => {
    const posted: unknown[] = [];
    const loop = new PayloadLoop(async () => undefined, (p) => posted.push(p), () => 10_000);
    loop.attach('b', 'r1');
    loop.pageReady({ layer: LAYER } as unknown as BoardRevision);
    loop.received({ ...GOOD });
    expect(loop.payload).toEqual(GOOD);
    loop.received(withValue('ghost', 1));
    expect(loop.payload).toEqual(GOOD);
    expect(loop.draftRefused).toBe(true);
  });
});
