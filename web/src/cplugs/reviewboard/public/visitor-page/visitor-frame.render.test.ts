/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import bridgeSource from '../../../../../../src/cplugs/reviewboard/bridge.js?raw';
import fieldsSource from '../../../../../../src/cplugs/reviewboard/frame/layer-fields.js?raw';
import moreSource from '../../../../../../src/cplugs/reviewboard/frame/layer-fields-more.js?raw';
import rowsSource from '../../../../../../src/cplugs/reviewboard/frame/layer-rows.js?raw';
import coreSource from '../../../../../../src/cplugs/reviewboard/frame/layer-core.js?raw';
import PublicBoard from './PublicBoard.svelte';
import type { BoardResult, PublicBoardData } from './board-client';
import type { WatchDocument } from './newer-watch';

const THEME = { '--oc-ground-page': 'rgb(10, 10, 10)', '--oc-text-primary': 'rgb(240, 240, 240)', '--oc-orange': 'rgb(255, 128, 0)' };
const OPTIONS = [{ id: 'a', label: 'alpha' }, { id: 'b', label: 'bravo' }, { id: 'c', label: 'charlie' }];
const QUESTIONS = { kind: 'questions', v: 1, title: 'sample', intro: 'answer what you can', placement: 'inline', items: [
  { id: 'like', kind: 'yesno', label: 'like it?' }, { id: 'beta', kind: 'toggle', label: 'beta' },
  { id: 'color', kind: 'choice', label: 'color', options: OPTIONS }, { id: 'feat', kind: 'multi', label: 'features', options: OPTIONS },
  { id: 'rank', kind: 'rank', label: 'rank', options: OPTIONS }, { id: 'score', kind: 'number', label: 'score' },
  { id: 'vol', kind: 'slider', label: 'volume', min: 0, max: 100 }, { id: 'when', kind: 'date', label: 'when' },
  { id: 'name', kind: 'text', label: 'name' }, { id: 'more', kind: 'longtext', label: 'more' },
] };
const ROWS = { kind: 'rows', v: 1, title: 'rows', pick: 'one', choices: [{ id: 'ok', label: 'fine', tone: 'ok' }, { id: 'push', label: 'push back', tone: 'push' }],
  rows: [{ id: 'r1', title: 'widget menu', suggest: 'ok', group: 'open' }, { id: 'r2', title: 'sidebar', group: 'open' }] };
const KEY_SHAPE = /\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){2,}\b/i;
const VISIBLE: WatchDocument = { hidden: false, addEventListener: () => undefined, removeEventListener: () => undefined };

type Json = Record<string, unknown>;
type Listener = (event: { source?: unknown; data?: unknown; type?: string; detail?: unknown }) => void;
let app: ReturnType<typeof mount> | null = null;

async function openTogether(layer: Json): Promise<{ doc: Document; fake: Json }> {
  const board: PublicBoardData = { title: 'menu', revision: 'r1', viewport: 600, views: [{ id: 'main', label: 'main', frame: '/f/t' }], prompts: [], layer,
    access: 'answer', theme: THEME, draft: null };
  const load = async (): Promise<BoardResult> => ({ kind: 'board', board });
  app = mount(PublicBoard, { target: document.body, props: { load, send: async () => ({ kind: 'received', duplicate: false } as const),
    save: async () => ({ kind: 'saved', changed: true } as const), wait: async () => ({ kind: 'fixed' } as const), doc: VISIBLE } });
  for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
  const iframe = document.querySelector('iframe') as HTMLIFrameElement;
  const doc = document.implementation.createHTMLDocument('frame');
  doc.body.innerHTML = `<main data-rb-layer-root></main><script type="application/json" id="rb-layer">${JSON.stringify(layer)}</script>`;
  const listeners = new Map<string, Listener[]>();
  const parent = { postMessage: (data: unknown): void => { window.dispatchEvent(new MessageEvent('message', { data, origin: 'null', source: iframe.contentWindow })); } };
  const fake: Json = {
    parent,
    addEventListener: (type: string, fn: Listener) => listeners.set(type, [...(listeners.get(type) ?? []), fn]),
    dispatchEvent: (event: Event) => (listeners.get(event.type) ?? []).forEach((fn) => fn(event as unknown as Parameters<Listener>[0])),
  };
  vi.spyOn(iframe.contentWindow as Window, 'postMessage').mockImplementation(((message: unknown) => {
    const data = structuredClone(message);
    (listeners.get('message') ?? []).forEach((fn) => fn({ source: parent, data }));
  }) as Window['postMessage']);
  new Function('window', 'document', 'setTimeout', 'clearTimeout', bridgeSource)(fake, doc, setTimeout, clearTimeout);
  new Function('window', 'document', `(function () {\n${fieldsSource}\n${moreSource}\n${rowsSource}\n${coreSource}\n})();`)(fake, doc);
  doc.dispatchEvent(new Event('DOMContentLoaded'));
  for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
  return { doc, fake };
}

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} }));
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  document.documentElement.removeAttribute('style');
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('the questions layer in a visitor\'s frame', () => {
  it('wears the owner\'s palette: the frame\'s root carries the page ground the owner sees', async () => {
    const { doc } = await openTogether(QUESTIONS);
    expect(doc.documentElement.style.getPropertyValue('--oc-ground-page')).toBe(THEME['--oc-ground-page']);
    expect(document.documentElement.style.getPropertyValue('--oc-ground-page')).toBe(THEME['--oc-ground-page']);
  });

  it('draws every field kind with sentences, never a catalog key', async () => {
    const { doc } = await openTogether(QUESTIONS);
    expect(doc.querySelectorAll('.rbl-item, [data-rbl-item]').length).toBeGreaterThanOrEqual(QUESTIONS.items.length);
    expect(doc.body.textContent ?? '').not.toMatch(KEY_SHAPE);
    expect(doc.querySelector('.rbl-notekey')?.textContent).toBe('note');
  });
});

describe('the rows layer in a visitor\'s frame', () => {
  it('wears the palette and draws sentences, never a catalog key', async () => {
    const { doc } = await openTogether(ROWS);
    expect(doc.documentElement.style.getPropertyValue('--oc-ground-page')).toBe(THEME['--oc-ground-page']);
    expect(doc.querySelectorAll('[data-rbl-item]').length).toBe(ROWS.rows.length);
    expect(doc.body.textContent ?? '').not.toMatch(KEY_SHAPE);
  });
});

describe('the page itself', () => {
  it('draws no catalog key as text on a board with a layer', async () => {
    await openTogether(QUESTIONS);
    expect(document.body.textContent ?? '').not.toMatch(KEY_SHAPE);
  });
});
