/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TerminalSurface from './TerminalSurface.svelte';
import App from './App.svelte';
import { viewport } from './engine/viewport.svelte';

type Entry = { target: Element; contentRect: { width: number; height: number } };
const callbacks: ((entries: Entry[]) => void)[] = [];
const boxes = new Map<Element, { width: number; height: number }>();
const mounted: ReturnType<typeof mount>[] = [];

class FakeObserver {
  constructor(cb: (entries: Entry[]) => void) {
    callbacks.push(cb);
  }
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const surfaceIn = (root: Element): HTMLElement => root.querySelector<HTMLElement>('.oc-surface')!;

async function resize(el: Element, width: number, height: number): Promise<void> {
  boxes.set(el, { width, height });
  for (const cb of callbacks) cb([{ target: el, contentRect: { width, height } }]);
  await new Promise((resolve) => setTimeout(resolve, 0));
  flushSync();
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', FakeObserver);
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => setTimeout(() => fn(0), 0));
  Element.prototype.getBoundingClientRect = function (this: Element) {
    const box = boxes.get(this) ?? { width: 0, height: 0 };
    return { ...box, top: 0, left: 0, right: box.width, bottom: box.height, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
  };
  viewport.wide = true;
  viewport.phone = false;
});
afterEach(async () => {
  for (const one of mounted.splice(0)) await unmount(one);
  document.body.replaceChildren();
  boxes.clear();
  callbacks.length = 0;
  vi.unstubAllGlobals();
});

test('the terminal surface keeps its row when the home surface goes hidden under it', async () => {
  const terminalHost = document.body.appendChild(document.createElement('div'));
  const homeHost = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(TerminalSurface, { target: terminalHost }));
  mounted.push(mount(App, { target: homeHost }));
  flushSync();
  const terminal = surfaceIn(terminalHost);
  const home = surfaceIn(homeHost);

  await resize(terminal, 468, 883);
  expect(terminal.querySelector('.oc-row'), 'the terminal surface never drew its row').not.toBeNull();

  await resize(home, 468, 883);
  await resize(home, 0, 0);
  expect(terminal.querySelector('.oc-row'), 'the terminal surface lost its row when Home went hidden').not.toBeNull();
});
