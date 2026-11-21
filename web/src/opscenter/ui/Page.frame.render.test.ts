/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, tick, unmount } from 'svelte';
import type { Snippet } from 'svelte';
import Page from './Page.svelte';
import InsetFindFixture from './InsetFindFixture.svelte';
import type { PageFrame } from './page-frame';
import { viewport } from '../engine/viewport.svelte';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
  viewport.narrow = false;
});

/** A snippet that draws one fixed fragment. Inputs: html (str). Output: Snippet. */
const snip = (html: string): Snippet => createRawSnippet(() => ({ render: () => html }));

function show(props: Record<string, unknown>): HTMLElement {
  app = mount(Page, { target: document.body, props: { title: 'Plugins', frame: 'column' satisfies PageFrame, ...props } });
  flushSync();
  return document.querySelector('.oc-page') as HTMLElement;
}

const regions = (root: HTMLElement): string[] => [...root.querySelectorAll('[data-frame-region]')].map((n) => n.getAttribute('data-frame-region') ?? '');

const FILL = { children: snip('<p id="x">body</p>'), tabs: snip('<i>tabs</i>'), bar: snip('<i>tools</i>'), notes: snip('<i>notes</i>'), foot: snip('<i>foot</i>') };

test('column: header, tab row, tool row, notes, body, foot, in that order, children in the frame scroller', () => {
  const root = show({ frame: 'column' satisfies PageFrame, ...FILL });
  expect(root.dataset.frame).toBe('column');
  expect(regions(root)).toEqual(['header', 'tabs', 'tools', 'notes', 'body', 'foot']);
  expect(root.querySelector('[data-frame-region=body] > .oc-page__scroll > .oc-page__main > #x')).not.toBeNull();
  expect(root.querySelector('[data-frame-region=side], [data-frame-region=detail]')).toBeNull();
});

test('column with a detail: the detail sits inside the body, under the header, with a frame-drawn head and close key', () => {
  let closed = 0;
  const root = show({ frame: 'column', ...FILL, detail: snip('<p id="d">item</p>'), detailTitle: 'item one', detailActions: snip('<b id="a">act</b>'), onDetailClose: () => closed++ });
  expect(regions(root)).toEqual(['header', 'tabs', 'tools', 'notes', 'body', 'detail', 'foot']);
  const detail = root.querySelector('[data-frame-region=body] > [data-frame-region=detail]') as HTMLElement;
  expect(detail).not.toBeNull();
  expect(detail.querySelector('.oc-page__detail-title')?.textContent).toBe('item one');
  expect(detail.querySelector('#a')).not.toBeNull();
  expect(detail.querySelector('.oc-page__detail-body #d')).not.toBeNull();
  (detail.querySelector('.oc-page__detail-head [data-btn]') as HTMLElement).click();
  expect(closed).toBe(1);
  expect(root.querySelector('.oc-page__body--detail')).not.toBeNull();
});

test('nav: the side runs beside one column of tool row, notes and body; the detail is its third region', () => {
  const root = show({ frame: 'nav', ...FILL, side: snip('<nav id="s">lens</nav>'), detail: snip('<p>d</p>'), detailTitle: 'd' });
  expect(regions(root)).toEqual(['header', 'frame', 'side', 'tabs', 'tools', 'notes', 'body', 'detail', 'foot']);
  const frame = root.querySelector('[data-frame-region=frame]') as HTMLElement;
  expect(frame.children[0]?.matches('[data-frame-region=side]')).toBe(true);
  expect(frame.children[1]?.classList.contains('oc-page__col')).toBe(true);
  expect(frame.children[2]?.matches('[data-frame-region=detail]')).toBe(true);
  expect(root.querySelector('[data-frame-region=header]')?.parentElement).toBe(root);
});

test('nav with scroll=self marks the frame itself, so the frame keeps its fixed box down to the phone line (page-frames.css)', () => {
  const self = show({ frame: 'nav', scroll: 'self', children: snip('<p id="x">c</p>'), side: snip('<nav>lens</nav>') });
  expect(self.querySelector('[data-frame-region=frame]')?.getAttribute('data-scroll')).toBe('self');
  expect(self.querySelector('[data-frame-region=frame] > .oc-page__col > [data-frame-region=body][data-scroll=self] > .oc-page__fill > #x')).not.toBeNull();
  if (app) unmount(app);
  document.body.replaceChildren();
  const scroller = show({ frame: 'nav', children: snip('<p>c</p>'), side: snip('<nav>lens</nav>') });
  expect(scroller.querySelector('[data-frame-region=frame]')?.getAttribute('data-scroll')).toBe('frame');
});

test('nav without a bar still draws the phone picker row, labelled with the current side item', () => {
  const root = show({ frame: 'nav', children: snip('<p>b</p>'), side: snip('<nav>lens</nav>'), sideLabel: 'all projects' });
  const row = root.querySelector('.oc-page__bar--picker') as HTMLElement;
  expect(row).not.toBeNull();
  expect(row.querySelector('.oc-page__picker [data-btn]')?.textContent?.trim()).toBe('all projects');
  const picker = row.querySelector('.oc-page__picker [data-btn]') as HTMLElement;
  picker.click();
  flushSync();
  expect(root.querySelector('[data-frame-region=side]')?.hasAttribute('data-open')).toBe(true);
});

test('canvas and scroll=self get one fixed fill box, no scroller and no main column', () => {
  for (const props of [{ frame: 'canvas' }, { frame: 'column', scroll: 'self' }]) {
    const root = show({ ...props, children: snip('<p id="x">c</p>') });
    expect(root.querySelector('[data-frame-region=body]')?.getAttribute('data-scroll')).toBe('self');
    expect(root.querySelector('.oc-page__body > .oc-page__fill > #x')).not.toBeNull();
    expect(root.querySelector('.oc-page__scroll, .oc-page__main')).toBeNull();
    unmount(app!);
    app = null;
    document.body.replaceChildren();
  }
});

test('the header search is one slot: in the header on a desktop, the omnibar on a phone, never twice', () => {
  const find = snip('<input id="f" />');
  const wide = show({ frame: 'column', children: snip('<p>b</p>'), find });
  expect(wide.querySelectorAll('#f')).toHaveLength(1);
  expect(wide.querySelector('[data-frame-region=header] > [data-frame-region=find] #f')).not.toBeNull();
  expect(wide.querySelector('.oc-titlebar--find')).not.toBeNull();
  expect(wide.querySelector('[role=search][data-frame-region=find] #f')).not.toBeNull();
  unmount(app!);
  document.body.replaceChildren();
  viewport.narrow = true;
  const narrow = show({ frame: 'column', children: snip('<p>b</p>'), find });
  expect(narrow.querySelectorAll('#f')).toHaveLength(1);
  expect(narrow.querySelector('[data-frame-region=find]')).toBeNull();
  expect(narrow.querySelector('.oc-titlebar__omni #f')).not.toBeNull();
  expect(narrow.querySelector('.oc-titlebar__omni [role=search] #f')).not.toBeNull();
});

test('a framed page declares the base button density on its header regions and sizes no button itself', () => {
  const root = show({ frame: 'column', ...FILL, detail: snip('<p>d</p>'), detailTitle: 'd' });
  const declared = [...root.querySelectorAll('[data-btn-density=frame]')].map((n) => n.getAttribute('data-frame-region') ?? n.className);
  expect(declared).toEqual(['header', 'tabs', 'tools', 'oc-page__detail-head']);
  expect(root.querySelector('[data-frame-region=body]')?.hasAttribute('data-btn-density')).toBe(false);
  for (const btn of root.querySelectorAll('[data-btn]')) expect((btn as HTMLElement).style.cssText).toBe('');
});

function openSheet(): HTMLElement {
  const root = show({ frame: 'nav', children: snip('<p>b</p>'), side: snip('<nav><a href="#x" id="pick">lens</a><input id="q" /></nav>'), sideLabel: 'all' });
  (root.querySelector('.oc-page__picker [data-btn]') as HTMLElement).click();
  flushSync();
  return root;
}

test('the side sheet: the picker names it with aria-controls and aria-expanded, and the sheet carries its own close key', () => {
  const root = openSheet();
  const picker = root.querySelector('.oc-page__picker [data-btn]') as HTMLElement;
  const side = root.querySelector('[data-frame-region=side]') as HTMLElement;
  expect(picker.getAttribute('aria-controls')).toBe(side.id);
  expect(picker.getAttribute('aria-expanded')).toBe('true');
  expect(side.hasAttribute('data-open')).toBe(true);
  (side.querySelector('.oc-page__sheet-head [data-btn]') as HTMLElement).click();
  flushSync();
  expect(side.hasAttribute('data-open')).toBe(false);
  expect(picker.getAttribute('aria-expanded')).toBe('false');
});

test('the side sheet over a scrolled page root is brought into view, and closing it without a pick puts the scroll back', async () => {
  const root = show({ frame: 'nav', children: snip('<p>b</p>'), side: snip('<nav><a href="#x" id="pick">lens</a></nav>'), sideLabel: 'all' });
  let top = 1200;
  Object.defineProperty(root, 'scrollTop', { configurable: true, get: () => top, set: (v: number) => (top = v) });
  const side = root.querySelector('[data-frame-region=side]') as HTMLElement;
  const into = vi.fn(() => (top = 300));
  side.scrollIntoView = into;
  const picker = root.querySelector('.oc-page__picker [data-btn]') as HTMLElement;
  picker.click();
  flushSync();
  await tick();
  expect(into).toHaveBeenCalledWith({ block: 'start' });
  expect(top).toBe(300);
  side.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(top).toBe(1200);
  top = 0;
  into.mockClear();
  picker.click();
  flushSync();
  await tick();
  expect(into).not.toHaveBeenCalled();
});

test('the side sheet closes on Escape (and the event stops there) and on picking an item, but not on typing in a field', () => {
  const root = openSheet();
  const side = root.querySelector('[data-frame-region=side]') as HTMLElement;
  (side.querySelector('#q') as HTMLElement).click();
  flushSync();
  expect(side.hasAttribute('data-open')).toBe(true);
  let reached = false;
  document.body.addEventListener('keydown', () => (reached = true), { once: true });
  side.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(side.hasAttribute('data-open')).toBe(false);
  expect(reached).toBe(false);
  (root.querySelector('.oc-page__picker [data-btn]') as HTMLElement).click();
  flushSync();
  (side.querySelector('#pick') as HTMLElement).click();
  flushSync();
  expect(side.hasAttribute('data-open')).toBe(false);
});

test('crossing the phone line keeps the search focus: the input remounts and the frame gives the focus back', async () => {
  const find = snip('<input id="f" />');
  const root = show({ frame: 'column', children: snip('<p>b</p>'), find });
  (root.querySelector('#f') as HTMLInputElement).focus();
  expect(document.activeElement?.id).toBe('f');
  viewport.narrow = true;
  flushSync();
  await tick();
  await tick();
  expect(root.querySelector('.oc-titlebar__omni #f')).not.toBeNull();
  expect(document.activeElement).toBe(root.querySelector('#f'));
});

test('an inset page has no title strip, so the header search is refused there with a warning', () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
  app = mount(InsetFindFixture, { target: document.body });
  flushSync();
  expect(document.querySelector('#f')).toBeNull();
  expect(warn).toHaveBeenCalledWith('page-find-on-inset', 'hosts');
  warn.mockRestore();
});
