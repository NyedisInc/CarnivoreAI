/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import source from '../../../../src/cplugs/reviewboard/bridge.js?raw';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

type Listener = (event: { source: unknown; data: unknown }) => void;

let listeners: Listener[];
let events: Event[];
let fakeWindow: { parent: typeof parent; rb?: { send(payload: unknown): void } };
let parent: { postMessage: ReturnType<typeof vi.fn> };

function boot(): void {
  parent = { postMessage: vi.fn() };
  listeners = [];
  events = [];
  fakeWindow = { parent, addEventListener: (type: string, fn: Listener) => type === 'message' && listeners.push(fn), dispatchEvent: (e: Event) => events.push(e) } as unknown as typeof fakeWindow;
  new Function('window', 'document', 'setTimeout', 'clearTimeout', source)(fakeWindow, document, (fn: () => void, ms: number) => setTimeout(fn, ms), (id: number) => clearTimeout(id));
}

function deliver(data: unknown, from: unknown = parent): void {
  for (const fn of listeners) fn({ source: from, data });
}

beforeEach(() => {
  document.head.innerHTML = '<style>.x { color: var(--oc-orange); }</style>';
  document.body.innerHTML = '<button data-rb-anchor="send">send</button><span data-rb-anchor="Bad Id">x</span><p id="plain">plain</p>';
  document.documentElement.removeAttribute('data-theme-id');
  document.documentElement.removeAttribute('style');
});

afterEach(() => vi.useRealTimers());

describe('the frame points', () => {
  it('says ready with the anchors it tags and whether it reads app colors', () => {
    boot();
    expect(parent.postMessage).toHaveBeenCalledWith({ rb: 1, type: 'ready', anchors: ['send'], theme_aware: true }, '*');
  });

  it('reports a page that ignores themes', () => {
    document.head.innerHTML = '<style>.x { color: #123456; }</style>';
    boot();
    expect(parent.postMessage.mock.calls[0]![0]).toMatchObject({ type: 'ready', theme_aware: false });
  });

  it('reports a tap on a tagged element, and on nothing else', () => {
    boot();
    parent.postMessage.mockClear();
    document.getElementById('plain')!.click();
    expect(parent.postMessage).not.toHaveBeenCalled();
    (document.querySelector('[data-rb-anchor="send"]') as HTMLElement).click();
    expect(parent.postMessage).toHaveBeenCalledWith({ rb: 1, type: 'anchor', anchor: 'send' }, '*');
  });
});

describe('the frame obeys only its parent', () => {
  it('ignores a message from any other window, however well formed', () => {
    boot();
    deliver({ rb: 1, type: 'theme', id: 'evil', vars: { '--oc-orange': 'red' } }, { other: true });
    expect(document.documentElement.getAttribute('data-theme-id')).toBeNull();
  });

  it('sets a theme through setProperty, id on the root, and refuses unsafe names and values', () => {
    boot();
    deliver({ rb: 1, type: 'theme', id: 'dracula', vars: {
      '--oc-orange': '#ff9d00', '--oc-ground': 'rgb(1, 2, 3)', 'color': 'red', '--bad name': 'x', '--oc-a': 'red; background: url(http://evil/x)',
      '--oc-b': 'url(http://evil/x)', '--oc-c': '}</style><script>x</script>', '--oc-d': 'url(data:image/svg+xml,%3Csvg%3E%3C/svg%3E)',
    } });
    const root = document.documentElement;
    expect(root.getAttribute('data-theme-id')).toBe('dracula');
    expect(root.style.getPropertyValue('--oc-orange')).toBe('#ff9d00');
    expect(root.style.getPropertyValue('--oc-ground')).toBe('rgb(1, 2, 3)');
    expect(root.style.getPropertyValue('--oc-d')).toContain('data:image/svg+xml');
    for (const refused of ['color', '--bad name', '--oc-a', '--oc-b', '--oc-c']) expect(root.style.getPropertyValue(refused)).toBe('');
  });

  it('refuses a message that is not version 1, too large, or has a bad theme id', () => {
    boot();
    deliver({ rb: 2, type: 'theme', id: 'a', vars: { '--oc-x': 'red' } });
    deliver({ rb: 1, type: 'theme', id: 'a', vars: { '--oc-x': 'red' }, pad: 'x'.repeat(49 * 1024) });
    deliver({ rb: 1, type: 'theme', id: 'bad id!', vars: { '--oc-x': 'red' } });
    deliver('theme');
    expect(document.documentElement.style.getPropertyValue('--oc-x')).toBe('');
    expect(document.documentElement.getAttribute('data-theme-id')).toBeNull();
  });

  it('applies a whole palette, far over 4 KiB, because a theme message may carry up to 48 KiB (the header theme picker)', () => {
    boot();
    const vars: Record<string, string> = {};
    for (let i = 0; i < 400; i += 1) vars[`--oc-token-${String(i).padStart(3, '0')}`] = `rgb(${i % 256}, 20, 30)`;
    expect(JSON.stringify(vars).length).toBeGreaterThan(4096);
    deliver({ rb: 1, type: 'theme', id: 'carnivore', vars });
    const root = document.documentElement;
    expect(root.getAttribute('data-theme-id')).toBe('carnivore');
    expect(root.style.getPropertyValue('--oc-token-000')).toBe('rgb(0, 20, 30)');
    expect(root.style.getPropertyValue('--oc-token-399')).toBe('rgb(143, 20, 30)');
  });

  it('marks answered and noted anchors, and outlines a highlighted one for two seconds', () => {
    boot();
    const send = document.querySelector('[data-rb-anchor="send"]') as HTMLElement;
    deliver({ rb: 1, type: 'state', answered_anchors: ['send'], noted_anchors: [] });
    expect(send.hasAttribute('data-rb-answered')).toBe(true);
    expect(send.hasAttribute('data-rb-noted')).toBe(false);
    vi.useFakeTimers();
    deliver({ rb: 1, type: 'highlight', anchor: 'send' });
    expect(send.hasAttribute('data-rb-highlight')).toBe(true);
    vi.advanceTimersByTime(2100);
    expect(send.hasAttribute('data-rb-highlight')).toBe(false);
    deliver({ rb: 1, type: 'highlight', anchor: 'nothing' });
  });
});

describe('a payload page (#1760)', () => {
  it('posts its state with rb.send, coalesced so the last state wins and a burst never trips the rate limit', () => {
    vi.useFakeTimers();
    boot();
    parent.postMessage.mockClear();
    for (let i = 1; i <= 30; i += 1) fakeWindow.rb!.send({ count: i });
    expect(parent.postMessage).not.toHaveBeenCalled();
    vi.advanceTimersByTime(120);
    expect(parent.postMessage).toHaveBeenCalledTimes(1);
    expect(parent.postMessage).toHaveBeenCalledWith({ rb: 1, type: 'payload', payload: { count: 30 } }, '*');
  });

  it('never posts something that is not an object', () => {
    vi.useFakeTimers();
    boot();
    parent.postMessage.mockClear();
    for (const bad of [[1], 'x', 4, null, undefined]) fakeWindow.rb!.send(bad);
    vi.advanceTimersByTime(300);
    expect(parent.postMessage).not.toHaveBeenCalled();
  });

  it('redraws on a load from its parent: an rb-load event with the payload and save number', () => {
    boot();
    deliver({ rb: 1, type: 'load', payload: { items: { milk: true } }, save: 2 });
    expect(events).toHaveLength(1);
    expect((events[0] as CustomEvent).type).toBe('rb-load');
    expect((events[0] as CustomEvent).detail).toEqual({ payload: { items: { milk: true } }, save: 2 });
  });

  it('takes a load larger than 4 KiB (a payload may be 64 KiB) but refuses one from another window or with a non-object payload', () => {
    boot();
    deliver({ rb: 1, type: 'load', payload: { pad: 'x'.repeat(20000) }, save: 1 });
    expect(events).toHaveLength(1);
    deliver({ rb: 1, type: 'load', payload: { a: 1 }, save: 1 }, { other: true });
    deliver({ rb: 1, type: 'load', payload: [1], save: 1 });
    deliver({ rb: 1, type: 'load', payload: 'x', save: 1 });
    deliver({ rb: 1, type: 'load', payload: { pad: 'x'.repeat(70000) }, save: 1 });
    expect(events).toHaveLength(1);
  });
});

describe("the app's scrollbar inside the page (#1760)", () => {
  it('puts one skin style first in head, reading the theme tokens, with no author CSS', () => {
    boot();
    const skin = document.head.firstElementChild as HTMLStyleElement;
    expect(skin.hasAttribute('data-rb-scrollbar')).toBe(true);
    expect(document.head.querySelectorAll('[data-rb-scrollbar]').length).toBe(1);
    for (const token of ['--oc-scrollbar-thumb-rest', '--oc-scrollbar-thumb-hover', '--oc-scrollbar-thumb-active', '--oc-scrollbar-track']) expect(skin.textContent).toContain(`var(${token}`);
    expect(skin.textContent).toContain('::-webkit-scrollbar-track, ::-webkit-scrollbar-corner { background-color: var(--oc-ground-page');
    expect(skin.textContent).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });

  it('does not make a theme-blind page look theme aware', () => {
    document.head.innerHTML = '<style>.x { color: #123456; }</style>';
    boot();
    expect(parent.postMessage.mock.calls[0]![0]).toMatchObject({ type: 'ready', theme_aware: false });
  });

  it('follows a theme change: the theme message sets the token the skin reads on the root', () => {
    boot();
    deliver({ rb: 1, type: 'theme', id: 'dracula', vars: { '--oc-scrollbar-thumb-rest': 'rgb(1, 2, 3)' } });
    expect(document.documentElement.style.getPropertyValue('--oc-scrollbar-thumb-rest')).toBe('rgb(1, 2, 3)');
    deliver({ rb: 1, type: 'theme', id: 'nord', vars: { '--oc-scrollbar-thumb-rest': 'rgb(9, 8, 7)' } });
    expect(document.documentElement.style.getPropertyValue('--oc-scrollbar-thumb-rest')).toBe('rgb(9, 8, 7)');
  });

  it("keeps the app's geometry (client/css/scrollbars.css is the source of truth)", () => {
    boot();
    const appScrollbars = readFileSync(resolve(process.cwd(), '../client/css/scrollbars.css'), 'utf8');
    const skin = (document.head.firstElementChild as HTMLStyleElement).textContent ?? '';
    for (const name of ['--scrollbar-size', '--scrollbar-inset', '--scrollbar-thumb-min']) {
      const pick = (css: string): string | undefined => new RegExp(`${name}:\\s*([0-9]+px)`).exec(css)?.[1];
      expect(pick(skin)).toBeDefined();
      expect(pick(skin)).toBe(pick(appScrollbars));
    }
  });
});
