/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import bridge from '../../../../src/cplugs/reviewboard/bridge.js?raw';

type Listener = (event: { source: unknown; data: unknown }) => void;

function examplePage(): string {
  const doc = readFileSync(resolve(__dirname, '../../../../docs/reviewboard.md'), 'utf8');
  const after = doc.slice(doc.indexOf('### Writing a payload page'));
  const match = /```html\n([\s\S]*?)```/.exec(after);
  if (!match) throw new Error('docs/reviewboard.md has no html example under "Writing a payload page"');
  return match[1]!;
}

let parent: { postMessage: ReturnType<typeof vi.fn> };
let listeners: Listener[];

function boot(): void {
  const page = examplePage();
  const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]!);
  document.documentElement.innerHTML = page.replace(/<script>[\s\S]*?<\/script>/g, '').replace(/<!doctype html>|<meta[^>]*>/gi, '');
  parent = { postMessage: vi.fn() };
  listeners = [];
  const events = new EventTarget();
  const frameWindow = {
    parent,
    addEventListener: (type: string, fn: Listener, opts?: unknown) =>
      type === 'message' ? listeners.push(fn) : events.addEventListener(type, fn as unknown as EventListener, opts as AddEventListenerOptions),
    dispatchEvent: (e: Event) => events.dispatchEvent(e),
  };
  new Function('window', 'document', 'setTimeout', 'clearTimeout', bridge)(frameWindow, document, setTimeout, clearTimeout);
  for (const code of scripts) new Function('window', 'document', code)(frameWindow, document);
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('the documented example page', () => {
  it('posts its whole state as a payload when a box changes', () => {
    boot();
    parent.postMessage.mockClear();
    const box = document.querySelector('[data-name="eggs"]') as HTMLInputElement;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    vi.advanceTimersByTime(150);
    expect(parent.postMessage).toHaveBeenCalledTimes(1);
    expect(parent.postMessage).toHaveBeenCalledWith({ rb: 1, type: 'payload', payload: { items: { eggs: true } } }, '*');
  });

  it('redraws a save it is handed and does not post it back', () => {
    boot();
    parent.postMessage.mockClear();
    for (const fn of listeners) fn({ source: parent, data: { rb: 1, type: 'load', payload: { items: { milk: true, tea: true } }, save: 2 } });
    const checked = [...document.querySelectorAll('input')].filter((b) => b.checked).map((b) => b.dataset.name);
    expect(checked).toEqual(['milk', 'tea']);
    vi.advanceTimersByTime(300);
    expect(parent.postMessage).not.toHaveBeenCalled();
  });
});
