/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import bridgeSource from '../../../../src/cplugs/reviewboard/bridge.js?raw';
import fieldsSource from '../../../../src/cplugs/reviewboard/frame/layer-fields.js?raw';
import moreSource from '../../../../src/cplugs/reviewboard/frame/layer-fields-more.js?raw';
import rowsSource from '../../../../src/cplugs/reviewboard/frame/layer-rows.js?raw';
import coreSource from '../../../../src/cplugs/reviewboard/frame/layer-core.js?raw';

type Listener = (event: { source?: unknown; data?: unknown; type?: string; detail?: unknown }) => void;
type Json = Record<string, unknown>;

const OPTIONS = [{ id: 'a', label: 'alpha' }, { id: 'b', label: 'bravo' }, { id: 'c', label: 'charlie' }];
const ITEMS = [
  { id: 'rail', kind: 'yesno', label: 'keep the rail?', anchor: 'send', required: true },
  { id: 'dense', kind: 'toggle', label: 'dense rows' },
  { id: 'density', kind: 'choice', label: 'density', group: 'look', options: OPTIONS, default: 'b' },
  { id: 'panels', kind: 'multi', label: 'panels', options: OPTIONS, min: 1, max: 2 },
  { id: 'name', kind: 'text', label: 'name', placeholder: 'a name' },
  { id: 'why', kind: 'longtext', label: 'why', anchor: 'ghost' },
  { id: 'order', kind: 'sketch', label: 'order', options: OPTIONS },
];
const LAYER = { kind: 'questions', v: 1, title: 'layout questions', intro: 'answer what you can', placement: 'inline', items: ITEMS };

const NAMES = ['yes', 'no', 'on', 'off', 'note', 'note_placeholder', 'show', 'unanswered', 'rank_up', 'rank_down', 'suggested', 'unsupported'];
let listeners: Map<string, Listener[]>;
let parent: { postMessage: ReturnType<typeof vi.fn> };
let fake: Record<string, unknown> & { rb?: { send(p: unknown): void } };

function boot(layer: Json = LAYER, body = '<button data-rb-anchor="send">send</button><p id="plain">page</p>', sent = true): void {
  document.head.innerHTML = '';
  document.body.innerHTML = `${body}<script type="application/json" id="rb-layer">${JSON.stringify(layer)}</script>`;
  parent = { postMessage: vi.fn() };
  listeners = new Map();
  fake = {
    parent,
    addEventListener: (type: string, fn: Listener) => listeners.set(type, [...(listeners.get(type) ?? []), fn]),
    dispatchEvent: (event: Event) => (listeners.get(event.type) ?? []).forEach((fn) => fn(event as unknown as Listener extends (e: infer E) => void ? E : never)),
  };
  new Function('window', 'document', 'setTimeout', 'clearTimeout', bridgeSource)(fake, document, setTimeout, clearTimeout);
  new Function('window', 'document', `(function () {\n${fieldsSource}\n${moreSource}\n${rowsSource}\n${coreSource}\n})();`)(fake, document);
  if (sent) deliver({ type: 'strings', map: Object.fromEntries(NAMES.map((n) => [`cplug.reviewboard.layer.${n}`, n.replace('_', ' ')])) });
}

function deliver(data: Json): void {
  (listeners.get('message') ?? []).forEach((fn) => fn({ source: parent, data: { rb: 1, ...data } }));
}

function posted(): Json[] {
  vi.advanceTimersByTime(150);
  return parent.postMessage.mock.calls.map((c) => c[0] as Json).filter((m) => m.type === 'payload').map((m) => m.payload as Json);
}

const item = (id: string): HTMLElement => document.querySelector(`[data-rbl-item="${id}"]`) as HTMLElement;
const pick = (id: string, label: string): HTMLButtonElement => [...item(id).querySelectorAll<HTMLButtonElement>('.rbl-opt')].find((b) => b.textContent === label)!;
const press = (el: HTMLElement): void => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })); };
const typeInto = (el: HTMLInputElement | HTMLTextAreaElement, text: string): void => { el.value = text; el.dispatchEvent(new Event('input', { bubbles: true })); };

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('each field posts the right value', () => {
  it('posts the whole state on the first edit, defaults included, and nothing before it', () => {
    boot();
    expect(posted()).toEqual([]);
    press(pick('rail', 'yes'));
    expect(posted().at(-1)).toEqual({ layer: 'questions', v: 1, values: { rail: true, dense: false, density: 'b' } });
  });

  it('yes and no are tri-state: the lit one clears when pressed again', () => {
    boot();
    press(pick('rail', 'no'));
    expect(posted().at(-1)).toMatchObject({ values: { rail: false } });
    press(pick('rail', 'no'));
    expect((posted().at(-1)!.values as Json).rail).toBeUndefined();
  });

  it('toggle, choice, multi, text and long text each post their value; an empty multi or text is left out', () => {
    boot();
    press(item('dense').querySelector('.rbl-switch') as HTMLElement);
    press(pick('density', 'charlie'));
    press(pick('panels', 'bravo'));
    press(pick('panels', 'alpha'));
    typeInto(item('name').querySelector('input')!, 'ada');
    typeInto(item('why').querySelector('textarea')!, 'because');
    expect(posted().at(-1)!.values).toEqual({ dense: true, density: 'c', panels: ['a', 'b'], name: 'ada', why: 'because' });
    press(pick('panels', 'alpha'));
    press(pick('panels', 'bravo'));
    typeInto(item('name').querySelector('input')!, '');
    expect(Object.keys(posted().at(-1)!.values as Json).sort()).toEqual(['dense', 'density', 'why']);
  });

  it('a multi locks the options past max but never refuses below min', () => {
    boot();
    press(pick('panels', 'alpha'));
    expect((posted().at(-1)!.values as Json).panels).toEqual(['a']);
    press(pick('panels', 'bravo'));
    expect(pick('panels', 'charlie').disabled).toBe(true);
    press(pick('panels', 'charlie'));
    expect((posted().at(-1)!.values as Json).panels).toEqual(['a', 'b']);
  });

  it('a note posts under notes and leaves the payload when emptied', () => {
    boot();
    press(item('rail').querySelector('.rbl-notekey') as HTMLElement);
    typeInto(item('rail').querySelector('.rbl-note') as HTMLTextAreaElement, 'only on desktop');
    expect(posted().at(-1)).toMatchObject({ notes: { rail: 'only on desktop' } });
    typeInto(item('rail').querySelector('.rbl-note') as HTMLTextAreaElement, '');
    expect(posted().at(-1)!.notes).toBeUndefined();
  });

  it('counts the required items that have no value', () => {
    boot();
    expect(document.querySelector('.rbl-count')!.textContent).toBe('1 unanswered');
    press(pick('rail', 'yes'));
    expect((document.querySelector('.rbl-count') as HTMLElement).hidden).toBe(true);
  });
});

describe('a redraw posts nothing back', () => {
  it('draws the saved state, drops a value that does not fit, and keeps a kind it cannot draw', () => {
    boot();
    deliver({ type: 'load', save: 2, payload: { layer: 'questions', v: 1, values: { rail: false, density: 'zzz', panels: ['c'], order: ['c', 'b', 'a'] }, notes: { name: 'n' } } });
    expect(pick('rail', 'no').getAttribute('aria-pressed')).toBe('true');
    expect(pick('density', 'bravo').getAttribute('aria-pressed')).toBe('false');
    expect(pick('panels', 'charlie').getAttribute('aria-pressed')).toBe('true');
    expect((item('name').querySelector('.rbl-note') as HTMLTextAreaElement).value).toBe('n');
    expect(posted()).toEqual([]);
    press(pick('rail', 'yes'));
    expect((posted().at(-1)!.values as Json).order).toEqual(['c', 'b', 'a']);
  });

  it('ignores a payload that is not this layer', () => {
    boot();
    deliver({ type: 'load', save: null, payload: { picks: { x: 1 } } });
    expect(pick('density', 'bravo').getAttribute('aria-pressed')).toBe('true');
  });
});

describe('placement', () => {
  it('draws an anchored item right after its part and an unknown anchor in the end section', () => {
    boot();
    const rail = item('rail');
    expect(document.querySelector('[data-rb-anchor="send"]')!.nextElementSibling).toBe(rail);
    expect(rail.classList.contains('rbl-item--inline')).toBe(true);
    expect(item('why').closest('.rbl-end')).not.toBeNull();
    expect(item('dense').closest('.rbl-end')).not.toBeNull();
    expect(document.querySelectorAll('.rbl-group').length).toBe(1);
  });

  it('puts two items on one part in item order, and finds a part the page adds late once the page has loaded', () => {
    boot({ ...LAYER, items: [{ id: 'one', kind: 'yesno', label: 'one', anchor: 'late' }, { id: 'two', kind: 'yesno', label: 'two', anchor: 'late' }] });
    expect(item('one').closest('.rbl-end')).not.toBeNull();
    document.body.insertAdjacentHTML('afterbegin', '<h2 data-rb-anchor="late">late</h2>');
    (listeners.get('load') ?? []).forEach((fn) => fn({}));
    const heading = document.querySelector('[data-rb-anchor="late"]')!;
    expect([heading.nextElementSibling, heading.nextElementSibling!.nextElementSibling]).toEqual([item('one'), item('two')]);
  });

  it('float puts every item in one panel, and show outlines the part through the bridge', () => {
    boot({ ...LAYER, placement: 'float' });
    const panel = document.querySelector('.rbl-float')!;
    expect(ITEMS.every((i) => panel.contains(item(i.id)))).toBe(true);
    press(item('rail').querySelector('.rbl-show') as HTMLElement);
    expect(document.querySelector('[data-rb-anchor="send"]')!.hasAttribute('data-rb-highlight')).toBe(true);
    press(panel.querySelector('.rbl-fold') as HTMLElement);
    expect(panel.classList.contains('rbl-float--closed')).toBe(true);
  });

  it('adds no data-rb-anchor of its own', () => {
    boot();
    expect(document.querySelectorAll('[data-rb-anchor]').length).toBe(1);
    const ready = parent.postMessage.mock.calls.map((c) => c[0] as Json).find((m) => m.type === 'ready')!;
    expect(ready.anchors).toEqual(['send']);
  });
});

describe('the frame stays closed', () => {
  it('leaves the page a no-op send, so only the runtime writes the payload', () => {
    boot();
    fake.rb!.send({ layer: 'questions', v: 1, values: { rail: true } });
    expect(posted()).toEqual([]);
  });

  it('draws a label as text, never as markup', () => {
    boot({ ...LAYER, items: [{ id: 'x', kind: 'yesno', label: '<img src=x onerror=1><b>hi</b>' }] });
    expect(item('x').querySelector('img, b')).toBeNull();
    expect(item('x').querySelector('.rbl-label')!.textContent).toBe('<img src=x onerror=1><b>hi</b>');
  });

  it('shows a missing string as its key and the sent string once the board has sent it; the bridge drops keys outside the layer', () => {
    boot(LAYER, undefined, false);
    expect(pick('rail', 'cplug.reviewboard.layer.yes')).toBeTruthy();
    let seen = { map: {} as Json };
    (fake.addEventListener as (t: string, f: Listener) => void)('rb-strings', (e) => { seen = e.detail as typeof seen; });
    deliver({ type: 'strings', map: { 'cplug.reviewboard.layer.yes': 'yes', 'cplug.reviewboard.layer.no': 'no', 'evil.key': 'x', 'cplug.reviewboard.layer.long': 'y'.repeat(400) } });
    expect(pick('rail', 'yes')).toBeTruthy();
    expect(item('rail').querySelector('.rbl-notekey')!.textContent).toBe('cplug.reviewboard.layer.note');
    expect(seen.map).toEqual({ 'cplug.reviewboard.layer.yes': 'yes', 'cplug.reviewboard.layer.no': 'no' });
  });

  it('shows a kind it cannot draw yet as its label and the unsupported line, with no control', () => {
    boot();
    expect(item('order').querySelector('.rbl-opts, input, textarea:not(.rbl-note)')).toBeNull();
    expect(item('order').textContent).toContain('unsupported');
  });

  it('draws nothing for a layer it does not know, and survives a broken data block', () => {
    boot({ ...LAYER, kind: 'sketch' });
    expect(document.querySelector('.rbl')).toBeNull();
    document.body.innerHTML = '<script type="application/json" id="rb-layer">{nope</script>';
    expect(() => new Function('window', 'document', `(function () {\n${fieldsSource}\n${moreSource}\n${rowsSource}\n${coreSource}\n})();`)(fake, document)).not.toThrow();
  });
});

describe('rank, number and date (S3)', () => {
  const RANKED = [{ id: 'a', label: 'alpha' }, { id: 'b', label: 'bravo' }, { id: 'c', label: 'charlie' }, { id: 'd', label: 'delta' }];
  const S3 = {
    kind: 'questions', v: 1, title: 's3', placement: 'inline',
    items: [
      { id: 'order', kind: 'rank', label: 'order', options: RANKED },
      { id: 'qty', kind: 'number', label: 'how many', min: 1, max: 10, unit: 'rows' },
      { id: 'vol', kind: 'number', label: 'volume', min: 0, max: 100, step: 5, slider: true, default: 40 },
      { id: 'when', kind: 'date', label: 'when', min: '2026-10-01', max: '2026-10-31' },
    ],
  };
  const entries = (id: string): HTMLElement[] => [...item(id).querySelectorAll<HTMLElement>('.rbl-rank__item')];
  const order = (id: string): string[] => entries(id).map((e) => e.getAttribute('data-rbl-id')!);
  const values = (): Json => posted().at(-1)!.values as Json;
  const fire = (target: Element, type: string, extra: Json = {}): void => { target.dispatchEvent(Object.assign(new Event(type, { bubbles: true, cancelable: true }), { button: 0, pointerId: 1 }, extra)); };
  const layout = (id: string): void => entries(id).forEach((e) => { e.getBoundingClientRect = () => { const top = order(id).indexOf(e.getAttribute('data-rbl-id')!) * 20; return { top, height: 20, bottom: top + 20 } as DOMRect; }; });

  it('draws a rank in the options order, with a position number on each entry, and posts nothing until the owner moves one', () => {
    boot(S3);
    expect(order('order')).toEqual(['a', 'b', 'c', 'd']);
    expect(entries('order').map((e) => e.querySelector('.rbl-rank__n')!.textContent)).toEqual(['1', '2', '3', '4']);
    expect(posted()).toEqual([]);
  });

  it('a drag by the grip posts the full new order', () => {
    boot(S3);
    layout('order');
    const grip = entries('order')[0]!.querySelector('.rbl-rank__grip')!;
    fire(grip, 'pointerdown', { clientY: 5 });
    fire(grip, 'pointermove', { clientY: 75 });
    fire(grip, 'pointerup', { clientY: 75 });
    expect(order('order')).toEqual(['b', 'c', 'd', 'a']);
    expect(values().order).toEqual(['b', 'c', 'd', 'a']);
  });

  it('a drag that ends where it began posts nothing', () => {
    boot(S3);
    layout('order');
    const grip = entries('order')[1]!.querySelector('.rbl-rank__grip')!;
    fire(grip, 'pointerdown', { clientY: 30 });
    fire(grip, 'pointermove', { clientY: 32 });
    fire(grip, 'pointerup', { clientY: 32 });
    expect(posted()).toEqual([]);
  });

  it('the arrow keys and the small buttons move an entry, keep it focused, and stop at the ends', () => {
    boot(S3);
    const second = entries('order')[1]!;
    second.focus();
    second.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    expect(values().order).toEqual(['a', 'c', 'b', 'd']);
    expect(document.activeElement).toBe(second);
    second.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true, cancelable: true }));
    second.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true, cancelable: true }));
    expect(order('order')).toEqual(['b', 'a', 'c', 'd']);
    const moveUp = entries('order')[0]!.querySelector<HTMLButtonElement>('.rbl-rank__move')!;
    press(moveUp);
    expect(order('order')).toEqual(['b', 'a', 'c', 'd']);
    press(entries('order')[3]!.querySelectorAll<HTMLButtonElement>('.rbl-rank__move')[0]!);
    expect(values().order).toEqual(['b', 'a', 'd', 'c']);
  });

  it('a saved rank that is not a full permutation is not drawn; a good one is', () => {
    boot(S3);
    deliver({ type: 'load', save: 1, payload: { layer: 'questions', v: 1, values: { order: ['a', 'b'] } } });
    expect(order('order')).toEqual(['a', 'b', 'c', 'd']);
    deliver({ type: 'load', save: 2, payload: { layer: 'questions', v: 1, values: { order: ['d', 'c', 'b', 'a'] } } });
    expect(order('order')).toEqual(['d', 'c', 'b', 'a']);
    expect(posted()).toEqual([]);
  });

  it('a number is clamped into min and max before it is posted, and an emptied field is left out', () => {
    boot(S3);
    const field = item('qty').querySelector('input')!;
    typeInto(field, '99');
    expect(values().qty).toBe(10);
    typeInto(field, '-4');
    expect(values().qty).toBe(1);
    typeInto(field, '7');
    expect(values().qty).toBe(7);
    typeInto(field, '');
    expect(values().qty).toBeUndefined();
    expect(item('qty').textContent).toContain('rows');
  });

  it('a number field rewrites an out of range entry on blur', () => {
    boot(S3);
    const field = item('qty').querySelector('input')!;
    typeInto(field, '99');
    field.dispatchEvent(new Event('change', { bubbles: true }));
    expect(field.value).toBe('10');
  });

  it('a slider shows its default, posts only when moved, and stays inside its bounds', () => {
    boot(S3);
    const slider = item('vol').querySelector<HTMLInputElement>('input[type=range]')!;
    expect(slider.value).toBe('40');
    expect(posted()).toEqual([]);
    typeInto(slider, '65');
    expect(values().vol).toBe(65);
    typeInto(slider, '500');
    expect(values().vol).toBeLessThanOrEqual(100);
  });

  it('a date in range posts; a date outside min and max is refused and the field goes back', () => {
    boot(S3);
    const field = item('when').querySelector<HTMLInputElement>('input[type=date]')!;
    field.value = '2026-10-12';
    field.dispatchEvent(new Event('change', { bubbles: true }));
    expect(values().when).toBe('2026-10-12');
    field.value = '2027-01-01';
    field.dispatchEvent(new Event('change', { bubbles: true }));
    expect(values().when).toBe('2026-10-12');
    expect(field.value).toBe('2026-10-12');
    field.value = '';
    field.dispatchEvent(new Event('change', { bubbles: true }));
    expect(values().when).toBeUndefined();
  });

  it('a saved number or date outside its bounds is not drawn', () => {
    boot(S3);
    deliver({ type: 'load', save: 1, payload: { layer: 'questions', v: 1, values: { qty: 50, when: '2020-01-01' } } });
    expect(item('qty').querySelector('input')!.value).toBe('');
    expect(item('when').querySelector<HTMLInputElement>('input')!.value).toBe('');
  });

  it('draws the same controls in the float panel, each with its note key', () => {
    boot({ ...S3, placement: 'float' });
    expect(document.querySelector('.rbl-float [data-rbl-item="order"] .rbl-rank')).not.toBeNull();
    for (const id of ['order', 'qty', 'vol', 'when']) expect(item(id).querySelector('.rbl-notekey')).not.toBeNull();
    expect(document.querySelector('.rbl-float [data-rbl-item="when"] input[type=date]')).not.toBeNull();
  });
});

describe('the rows layer (S4)', () => {
  const CHOICES = [{ id: 'ok', label: 'fine', tone: 'ok' }, { id: 'push', label: 'push back', tone: 'push' }, { id: 'later', label: 'later', tone: 'later' }];
  const ROWS = [
    { id: 'r1', title: 'widget menu', tag: 'removed', lines: [{ label: 'you had', text: 'presets' }, { label: 'now', text: '<b>none</b>' }], meta: 'abc123', group: 'NEW (1)', suggest: 'push', default: 'later' },
    { id: 'r2', title: 'sidebar colors', group: 'OPEN (2)', suggest: 'ok' },
    { id: 'r3', title: 'own picks', group: 'OPEN (2)', choices: [{ id: 'x', label: 'xray' }, { id: 'y', label: 'yankee' }] },
  ];
  const RLAYER = { kind: 'rows', v: 1, title: 'acme watch', pick: 'one', choices: CHOICES, rows: ROWS };
  const pick = (id: string, label: string): HTMLButtonElement => [...item(id).querySelectorAll<HTMLButtonElement>('.rbl-opt')].find((b) => b.querySelector('.rbl-opt__text')!.textContent === label)!;
  const values = (): Json => posted().at(-1)!.values as Json;

  it('draws every row with its title, tag, lines, footnote and group heading, as text only', () => {
    boot(RLAYER);
    expect(document.querySelectorAll('[data-rbl-item]').length).toBe(3);
    expect(item('r1').querySelector('.rbl-label')!.textContent).toBe('widget menu');
    expect(item('r1').querySelector('.rbl-chip')!.textContent).toBe('removed');
    expect([...item('r1').querySelectorAll('.rbl-line__label')].map((n) => n.textContent)).toEqual(['you had', 'now']);
    expect(item('r1').querySelector('b.rbl-line__text, .rbl-line__text b')).toBeNull();
    expect(item('r1').querySelector('.rbl-meta')!.textContent).toBe('abc123');
    expect([...document.querySelectorAll('.rbl-group')].map((n) => n.textContent)).toEqual(['NEW (1)', 'OPEN (2)']);
  });

  it("a row's own choices replace the layer's", () => {
    boot(RLAYER);
    expect([...item('r3').querySelectorAll('.rbl-opt')].map((b) => b.textContent)).toEqual(['xray', 'yankee']);
    expect([...item('r2').querySelectorAll('.rbl-opt')].map((b) => b.textContent)).toEqual(['finesuggested', 'push back', 'later']);
  });

  it('marks the suggestion and never picks it; a default pick shows lit', () => {
    boot(RLAYER);
    const marked = item('r1').querySelector('[data-rbl-suggest="true"]') as HTMLElement;
    expect(marked.textContent).toContain('push back');
    expect(marked.getAttribute('aria-pressed')).toBe('false');
    expect(item('r2').querySelector('[aria-pressed="true"]')).toBeNull();
    expect((item('r1').querySelector('[aria-pressed="true"]') as HTMLElement).textContent).toBe('later');
  });

  it('posts a pick as values and a note as notes, the carried default included, and clears a pick pressed twice', () => {
    boot(RLAYER);
    expect(posted()).toEqual([]);
    press(pick('r3', 'yankee'));
    let p = posted().at(-1)!;
    expect(p).toEqual({ layer: 'rows', v: 1, values: { r1: 'later', r3: 'y' } });
    typeInto(item('r2').querySelector('textarea') as HTMLTextAreaElement, 'ask acme');
    p = posted().at(-1)!;
    expect(p.notes).toEqual({ r2: 'ask acme' });
    press(pick('r3', 'yankee'));
    expect(values()).toEqual({ r1: 'later' });
  });

  it('a pick-several layer posts a list in the choices order and drops an emptied row', () => {
    boot({ ...RLAYER, pick: 'several' });
    press(pick('r2', 'later'));
    press(pick('r2', 'fine'));
    expect(values().r2).toEqual(['ok', 'later']);
    press(pick('r2', 'fine'));
    press(pick('r2', 'later'));
    expect(values().r2).toBeUndefined();
  });

  it('redraws a saved state from rb-load and posts nothing; a saved pick outside the row choices is dropped', () => {
    boot(RLAYER);
    deliver({ type: 'load', payload: { layer: 'rows', v: 1, values: { r2: 'push', r3: 'ok' }, notes: { r2: 'saved' } } });
    expect(pick('r2', 'push back').getAttribute('aria-pressed')).toBe('true');
    expect(item('r3').querySelector('[aria-pressed="true"]')).toBeNull();
    expect((item('r2').querySelector('textarea') as HTMLTextAreaElement).value).toBe('saved');
    expect(posted()).toEqual([]);
  });

  it('renders a 42 row board in the shape of the team watch page (four groups) and survives one edit', () => {
    const many = Array.from({ length: 42 }, (_, i) => ({
      id: `aw-${String(i + 1).padStart(3, '0')}`, title: `#${i + 1} entry ${i + 1}`, tag: 'changed', group: ['NEW (4) removed-partial', 'NEW (4) changed', 'OPEN (38) removed', 'OPEN (38) minor'][i % 4]!,
      lines: [{ label: 'you had', text: 'x' }, { label: 'now', text: 'y' }, { label: 'way back', text: 'none' }, { label: 'my take', text: 'fine with it: z' }], suggest: 'ok',
    })).sort((a, b) => a.group.localeCompare(b.group));
    boot({ ...RLAYER, rows: many });
    expect(document.querySelectorAll('[data-rbl-item]').length).toBe(42);
    expect(document.querySelectorAll('.rbl-group').length).toBe(4);
    press(pick('aw-001', 'push back'));
    expect(values()).toEqual({ 'aw-001': 'push' });
  });
});

describe('the note key (fix after the visual check)', () => {
  const note = (id: string): HTMLTextAreaElement => item(id).querySelector('textarea.rbl-note') as HTMLTextAreaElement;
  const key = (id: string): HTMLElement => item(id).querySelector('.rbl-notekey') as HTMLElement;

  it('keeps an empty note hidden, and the key opens and closes it with aria-expanded', () => {
    boot();
    expect(note('rail').hidden).toBe(true);
    expect(key('rail').getAttribute('aria-expanded')).toBe('false');
    press(key('rail'));
    expect(note('rail').hidden).toBe(false);
    expect(key('rail').getAttribute('aria-expanded')).toBe('true');
    press(key('rail'));
    expect(note('rail').hidden).toBe(true);
    expect(key('rail').getAttribute('aria-expanded')).toBe('false');
    expect(key('rail').classList.contains('rbl-notekey--has')).toBe(false);
  });

  it('marks the key of an item that holds a note, and a saved note comes back open', () => {
    boot();
    press(key('rail'));
    typeInto(note('rail'), 'only on desktop');
    expect(key('rail').classList.contains('rbl-notekey--has')).toBe(true);
    press(key('rail'));
    expect(key('rail').classList.contains('rbl-notekey--has')).toBe(true);
    deliver({ type: 'load', payload: { layer: 'questions', v: 1, values: {}, notes: { dense: 'saved' } } });
    expect(note('dense').hidden).toBe(false);
    expect(key('dense').classList.contains('rbl-notekey--has')).toBe(true);
    expect(note('rail').hidden).toBe(true);
  });

  it('draws the layer title once', () => {
    boot();
    const drawn = [...document.querySelectorAll('.rbl')].map((n) => n.textContent!).join('');
    expect(drawn.split('layout questions').length - 1).toBe(1);
    expect(document.querySelectorAll('.rbl-title').length).toBe(1);
  });
});
