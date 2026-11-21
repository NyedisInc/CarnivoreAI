import { describe, expect, it, vi } from 'vitest';
import { MAX_MESSAGE_BYTES, MAX_PER_SECOND, createBridgeHost, type DropReason } from './bridge-host';
import { MAX_PAYLOAD_BYTES } from './payload-model';

function setup(declared: string[] = ['send', 'buttons']) {
  const win = { postMessage: vi.fn() };
  const other = { postMessage: vi.fn() };
  const frame = { contentWindow: win } as unknown as HTMLIFrameElement;
  let clock = 0;
  const handlers = { ready: vi.fn(), anchor: vi.fn(), payload: vi.fn(), dropped: vi.fn<(r: DropReason, n: number) => void>() };
  const bridge = createBridgeHost({ frame: () => frame, declared: () => declared, handlers, now: () => clock });
  const send = (data: unknown, over: { source?: unknown; origin?: string } = {}) =>
    bridge.handle({ source: ('source' in over ? over.source : win) as MessageEventSource, origin: over.origin ?? 'null', data });
  return { win, other, handlers, bridge, send, tick: (ms: number) => (clock += ms) };
}

describe('what the board accepts from the mockup frame', () => {
  it('takes a ready and an anchor from the frame itself, naming declared anchors only', () => {
    const { send, handlers } = setup();
    expect(send({ rb: 1, type: 'ready', anchors: ['send', 'nope'], theme_aware: false })).toBe(true);
    expect(handlers.ready).toHaveBeenCalledWith({ anchors: ['send'], themeAware: false });
    expect(send({ rb: 1, type: 'anchor', anchor: 'buttons' })).toBe(true);
    expect(handlers.anchor).toHaveBeenCalledWith('buttons');
  });

  it('DROPS a message from another source, whatever it says', () => {
    const { send, other, handlers } = setup();
    expect(send({ rb: 1, type: 'anchor', anchor: 'send' }, { source: other })).toBe(false);
    expect(send({ rb: 1, type: 'anchor', anchor: 'send' }, { source: null })).toBe(false);
    expect(handlers.anchor).not.toHaveBeenCalled();
    expect(handlers.dropped).toHaveBeenCalledWith('source', 1);
  });

  it('drops a message whose origin is not the opaque one', () => {
    const { send, handlers } = setup();
    expect(send({ rb: 1, type: 'anchor', anchor: 'send' }, { origin: 'https://evil.example' })).toBe(false);
    expect(handlers.anchor).not.toHaveBeenCalled();
  });

  it('drops an oversized body, a wrong shape, an unlisted type and an undeclared anchor', () => {
    const { send, handlers } = setup();
    expect(send({ rb: 1, type: 'anchor', anchor: 'send', pad: 'x'.repeat(MAX_MESSAGE_BYTES) })).toBe(false);
    expect(send({ rb: 2, type: 'anchor', anchor: 'send' })).toBe(false);
    expect(send('anchor')).toBe(false);
    expect(send(null)).toBe(false);
    expect(send({ rb: 1, type: 'pick', prompt: 'layout', option: 'a' })).toBe(false);
    expect(send({ rb: 1, type: 'anchor', anchor: 'secret' })).toBe(false);
    expect(handlers.anchor).not.toHaveBeenCalled();
    expect(handlers.dropped.mock.calls.map((c) => c[0])).toEqual(['size', 'shape', 'shape', 'shape', 'type', 'undeclared']);
  });

  it('drops a body that is not plain data (a cycle)', () => {
    const { send } = setup();
    const cyc: Record<string, unknown> = { rb: 1, type: 'anchor', anchor: 'send' };
    cyc.self = cyc;
    expect(send(cyc)).toBe(false);
  });

  it('allows 20 messages a second, drops the rest and reports the rate drop once', () => {
    const { send, handlers, tick } = setup();
    for (let i = 0; i < MAX_PER_SECOND; i += 1) expect(send({ rb: 1, type: 'anchor', anchor: 'send' })).toBe(true);
    for (let i = 0; i < 5; i += 1) expect(send({ rb: 1, type: 'anchor', anchor: 'send' })).toBe(false);
    expect(handlers.dropped.mock.calls.filter((c) => c[0] === 'rate')).toHaveLength(1);
    tick(1000);
    expect(send({ rb: 1, type: 'anchor', anchor: 'send' })).toBe(true);
  });

  it('drops everything while there is no frame', () => {
    const handlers = { ready: vi.fn(), anchor: vi.fn() };
    const bridge = createBridgeHost({ frame: () => null, declared: () => ['send'], handlers });
    expect(bridge.handle({ source: {} as MessageEventSource, origin: 'null', data: { rb: 1, type: 'anchor', anchor: 'send' } })).toBe(false);
    expect(handlers.anchor).not.toHaveBeenCalled();
  });
});

describe('what the board says to the frame', () => {
  it('posts highlight, state and theme as versioned messages', () => {
    const { bridge, win } = setup();
    bridge.highlight('send');
    bridge.state(['send'], []);
    bridge.theme('dracula', { '--oc-orange': '#fff' });
    expect(win.postMessage.mock.calls).toEqual([
      [{ rb: 1, type: 'highlight', anchor: 'send' }, '*'],
      [{ rb: 1, type: 'state', answered_anchors: ['send'], noted_anchors: [] }, '*'],
      [{ rb: 1, type: 'theme', id: 'dracula', vars: { '--oc-orange': '#fff' } }, '*'],
    ]);
  });
});

describe('a payload page (#1760): the frame supplies a payload, it can never save or send', () => {
  it('hands a valid payload to the board, from the frame itself only', () => {
    const { send, other, handlers } = setup();
    expect(send({ rb: 1, type: 'payload', payload: { items: { milk: true }, n: 2 } })).toBe(true);
    expect(handlers.payload).toHaveBeenCalledWith({ items: { milk: true }, n: 2 });
    expect(send({ rb: 1, type: 'payload', payload: { a: 1 } }, { source: other })).toBe(false);
    expect(send({ rb: 1, type: 'payload', payload: { a: 1 } }, { origin: 'https://evil.example' })).toBe(false);
    expect(handlers.payload).toHaveBeenCalledTimes(1);
  });

  it('has no message that saves or sends: every such type is dropped and no handler runs', () => {
    const { send, handlers } = setup();
    const save = vi.fn();
    for (const type of ['save', 'send', 'rb.save', 'rb.send', 'round', 'submit', 'draft', 'load']) {
      expect(send({ rb: 1, type, payload: { a: 1 }, note: 'x' })).toBe(false);
    }
    expect(handlers.payload).not.toHaveBeenCalled();
    expect(save).not.toHaveBeenCalled();
    expect(handlers.dropped.mock.calls.every((c) => c[0] === 'type')).toBe(true);
  });

  it('drops a payload that is not a JSON object, is over 64 KiB, is nested too deep, or is a cycle', () => {
    const { send, handlers, tick } = setup();
    for (const bad of [[1, 2], 'text', 7, null, undefined]) {
      expect(send({ rb: 1, type: 'payload', payload: bad })).toBe(false);
      tick(100);
    }
    expect(send({ rb: 1, type: 'payload', payload: { pad: 'x'.repeat(MAX_PAYLOAD_BYTES) } })).toBe(false);
    tick(1000);
    let deep: Record<string, unknown> = {};
    const top = deep;
    for (let i = 0; i < 40; i += 1) deep = (deep.n = {});
    expect(send({ rb: 1, type: 'payload', payload: top })).toBe(false);
    const cycle: Record<string, unknown> = { a: 1 };
    cycle.self = cycle;
    expect(send({ rb: 1, type: 'payload', payload: cycle })).toBe(false);
    expect(handlers.payload).not.toHaveBeenCalled();
    expect(handlers.dropped.mock.calls.map((c) => c[0]).every((r) => r === 'payload' || r === 'size')).toBe(true);
  });

  it('takes a payload right at the cap but holds every other message to 4 KiB', () => {
    const { send, handlers } = setup();
    const ok = { pad: 'x'.repeat(MAX_PAYLOAD_BYTES - 20) };
    expect(send({ rb: 1, type: 'payload', payload: ok })).toBe(true);
    expect(handlers.payload).toHaveBeenCalledTimes(1);
    expect(send({ rb: 1, type: 'anchor', anchor: 'send', pad: 'x'.repeat(MAX_MESSAGE_BYTES) })).toBe(false);
  });

  it('hands the payload on as plain data (a JSON round trip), so nothing but JSON reaches the board', () => {
    const { send, handlers } = setup();
    const tricky = { a: 1, when: new Date(0), nothing: undefined, fn: () => 1 };
    expect(send({ rb: 1, type: 'payload', payload: tricky })).toBe(true);
    expect(handlers.payload.mock.calls[0]![0]).toEqual({ a: 1, when: '1970-01-01T00:00:00.000Z' });
  });

  it('posts a save back to the page as `load`, versioned, with the save number', () => {
    const { bridge, win } = setup();
    bridge.load({ items: { milk: true } }, 3);
    bridge.load({ items: {} }, null);
    expect(win.postMessage.mock.calls).toEqual([
      [{ rb: 1, type: 'load', payload: { items: { milk: true } }, save: 3 }, '*'],
      [{ rb: 1, type: 'load', payload: { items: {} }, save: null }, '*'],
    ]);
  });

  it('posts the layer runtime its strings, versioned', () => {
    const { bridge, win } = setup();
    bridge.strings({ 'cplug.reviewboard.layer.yes': 'yes' });
    expect(win.postMessage.mock.calls).toEqual([[{ rb: 1, type: 'strings', map: { 'cplug.reviewboard.layer.yes': 'yes' } }, '*']]);
  });
});
