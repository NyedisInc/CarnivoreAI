/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { createBridgeHost } from './bridge-host';

function cloningFrame() {
  const received: unknown[] = [];
  const win = { postMessage: (message: unknown) => received.push(structuredClone(message)) };
  const frame = { contentWindow: win } as unknown as HTMLIFrameElement;
  const bridge = createBridgeHost({
    frame: () => frame,
    declared: () => [],
    handlers: { ready: () => {}, anchor: () => {}, payload: () => {}, dropped: () => {} },
    now: () => 0,
  });
  return { bridge, received };
}

describe('loading a save back into the payload page (#1760)', () => {
  it('delivers a Svelte $state payload to the frame as plain data, without throwing', () => {
    const { bridge, received } = cloningFrame();
    const payload = $state({ items: { milk: true }, n: 2 });
    expect(() => bridge.load(payload, 1)).not.toThrow();
    expect(received).toEqual([{ rb: 1, type: 'load', payload: { items: { milk: true }, n: 2 }, save: 1 }]);
  });
});
