/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import source from '../../../../src/cplugs/reviewboard/bridge.js?raw';

type Listener = (event: { source: unknown; data: unknown }) => void;

let listeners: Listener[];
let parent: { postMessage: ReturnType<typeof vi.fn> };

function boot(): void {
  parent = { postMessage: vi.fn() };
  listeners = [];
  const fakeWindow = { parent, innerHeight: 600, addEventListener: (type: string, fn: Listener) => type === 'message' && listeners.push(fn), dispatchEvent: () => true };
  new Function('window', 'document', 'setTimeout', 'clearTimeout', source)(fakeWindow, document, (fn: () => void, ms: number) => setTimeout(fn, ms), (id: number) => clearTimeout(id));
}

function deliver(data: unknown, from: unknown = parent): void {
  for (const fn of listeners) fn({ source: from, data });
}

const spacers = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('[data-rb-gap]')];

beforeEach(() => {
  vi.useFakeTimers();
  document.head.innerHTML = '';
  document.body.innerHTML = '<div id="send" data-rb-anchor="send">send</div><table><tbody><tr data-rb-anchor="row"><td>x</td></tr></tbody></table><ul><li data-rb-anchor="item">i</li></ul><p id="plain">p</p>';
});
afterEach(() => vi.useRealTimers());

describe('making room for inline picks', () => {
  it('places an empty hidden spacer right after each named anchor, sized as asked', () => {
    boot();
    deliver({ rb: 1, type: 'gaps', gaps: { send: 90, item: 40 } });
    const [first, second] = spacers();
    expect(document.getElementById('send')!.nextElementSibling).toBe(first);
    expect(first!.style.height).toBe('90px');
    expect(first!.textContent).toBe('');
    expect(first!.getAttribute('aria-hidden')).toBe('true');
    expect(second!.tagName).toBe('LI');
    expect(second!.style.height).toBe('40px');
  });

  it('puts a table row after a table row, with the height on its one cell', () => {
    boot();
    deliver({ rb: 1, type: 'gaps', gaps: { row: 50 } });
    const [spacer] = spacers();
    expect(spacer!.tagName).toBe('TR');
    expect((spacer!.firstChild as HTMLElement).style.height).toBe('50px');
  });

  it('resizes the same spacer and takes back the room an id left out', () => {
    boot();
    deliver({ rb: 1, type: 'gaps', gaps: { send: 90, item: 40 } });
    deliver({ rb: 1, type: 'gaps', gaps: { send: 120 } });
    expect(spacers()).toHaveLength(1);
    expect(spacers()[0]!.style.height).toBe('120px');
    deliver({ rb: 1, type: 'gaps', gaps: {} });
    expect(spacers()).toHaveLength(0);
  });

  it('ignores a request from any other window, an unknown anchor, and a size no page should be given', () => {
    boot();
    deliver({ rb: 1, type: 'gaps', gaps: { send: 90 } }, { other: true });
    expect(spacers()).toHaveLength(0);
    deliver({ rb: 1, type: 'gaps', gaps: { nope: 90, send: 99999, item: -4, row: 'tall', 'Bad Id': 5 } });
    expect(spacers()).toHaveLength(0);
    deliver({ rb: 1, type: 'gaps', gaps: [1, 2] });
    expect(spacers()).toHaveLength(0);
  });
});

describe('telling the board where the room sits', () => {
  it('posts one layout after a request, with [x, y, width] for each asked-for gap', () => {
    boot();
    parent.postMessage.mockClear();
    deliver({ rb: 1, type: 'gaps', gaps: { send: 90 } });
    expect(parent.postMessage).not.toHaveBeenCalled();
    vi.advanceTimersByTime(100);
    expect(parent.postMessage).toHaveBeenCalledTimes(1);
    const message = parent.postMessage.mock.calls[0]![0] as { type: string; gaps: Record<string, number[]>; h: number };
    expect(message).toMatchObject({ rb: 1, type: 'layout', h: 600 });
    expect(Object.keys(message.gaps)).toEqual(['send']);
    expect(message.gaps.send).toHaveLength(3);
  });

  it('says nothing about a layout while the board has asked for no room', () => {
    boot();
    parent.postMessage.mockClear();
    vi.advanceTimersByTime(500);
    expect(parent.postMessage).not.toHaveBeenCalled();
  });
});
