import { describe, expect, it, vi } from 'vitest';
import { createBridgeHost, gapSpots, type GapLayout } from './bridge-host';

function setup(declared: string[] = ['send', 'buttons']) {
  const win = { postMessage: vi.fn() };
  const frame = { contentWindow: win } as unknown as HTMLIFrameElement;
  const handlers = { ready: vi.fn(), anchor: vi.fn(), layout: vi.fn<(s: GapLayout) => void>(), dropped: vi.fn() };
  const bridge = createBridgeHost({ frame: () => frame, declared: () => declared, handlers });
  const send = (data: unknown) => bridge.handle({ source: win as unknown as MessageEventSource, origin: 'null', data });
  return { win, handlers, bridge, send };
}

describe('where the frame says its inline gaps sit', () => {
  it('takes a layout for declared anchors only, three finite numbers each', () => {
    const { send, handlers } = setup();
    expect(send({ rb: 1, type: 'layout', gaps: { send: [4, 120, 300], secret: [0, 0, 5], buttons: [1, 'x', 3] }, h: 600 })).toBe(true);
    expect(handlers.layout).toHaveBeenCalledWith({ send: { x: 4, y: 120, w: 300 } });
  });

  it('drops a layout that is not an object of gaps', () => {
    const { send, handlers } = setup();
    expect(send({ rb: 1, type: 'layout', gaps: [1, 2, 3] })).toBe(false);
    expect(send({ rb: 1, type: 'layout' })).toBe(false);
    expect(handlers.layout).not.toHaveBeenCalled();
    expect(handlers.dropped).toHaveBeenCalledWith('shape', expect.any(Number));
  });

  it('refuses a coordinate no page could have, and clamps a negative width', () => {
    expect(gapSpots({ send: [0, 1e9, 10] }, new Set(['send']))).toEqual({});
    expect(gapSpots({ send: [0, 5, -3] }, new Set(['send']))).toEqual({ send: { x: 0, y: 5, w: 0 } });
  });
});

describe('the room the board asks of the frame', () => {
  it('posts gaps with every px held to the cap, rounded, and no non-number', () => {
    const { bridge, win } = setup();
    bridge.gaps({ send: 90.4, buttons: 99999, bad: Number.NaN });
    expect(win.postMessage).toHaveBeenCalledWith({ rb: 1, type: 'gaps', gaps: { send: 90, buttons: 1200 } }, '*');
  });

  it('takes the room back with an empty map', () => {
    const { bridge, win } = setup();
    bridge.gaps({});
    expect(win.postMessage).toHaveBeenCalledWith({ rb: 1, type: 'gaps', gaps: {} }, '*');
  });
});
