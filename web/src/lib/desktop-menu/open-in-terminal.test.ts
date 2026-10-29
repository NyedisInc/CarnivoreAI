/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';

const toasts: Array<{ text: string; kind: string }> = [];
vi.mock('../widgets-page/undo-toast', () => ({ showToast: (spec: { text: string; kind: string }) => { toasts.push(spec); } }));

import { canOpenInTerminal, openInTerminal } from './open-in-terminal';

function bridge(open: ((id: string) => Promise<unknown>) | null): void {
  (globalThis as { carnivoreDesktop?: unknown }).carnivoreDesktop = open ? { capabilities: ['openInTerminal'], openInTerminal: open } : undefined;
}

afterEach(() => {
  delete (globalThis as { carnivoreDesktop?: unknown }).carnivoreDesktop;
  toasts.length = 0;
});

describe('canOpenInTerminal', () => {
  test('absent in a browser tab (no bridge)', () => {
    expect(canOpenInTerminal('ses_1', 'local', 'carnivore_a')).toBe(false);
  });
  test('present for a local session with a tmux name in the desktop app', () => {
    bridge(async () => ({ opened: true }));
    expect(canOpenInTerminal('ses_1', 'local', 'carnivore_a')).toBe(true);
    expect(canOpenInTerminal('adopted:x', undefined, 'x')).toBe(true);
  });
  test('absent for a remote id, another computer\'s row, or a session with no tmux name', () => {
    bridge(async () => ({ opened: true }));
    expect(canOpenInTerminal('remote:peer-a:x', 'peer-a', 'x')).toBe(false);
    expect(canOpenInTerminal('ses_2', 'peer-a', 'x')).toBe(false);
    expect(canOpenInTerminal('ses_3', 'local', null)).toBe(false);
  });
});

describe('openInTerminal', () => {
  test('a refusal or a thrown error is one toast; a decline is silent; success is silent', async () => {
    bridge(async () => ({ opened: false, error: 'boom', reason: 'failed' }));
    await openInTerminal('ses_1');
    expect(toasts.map((t) => t.kind)).toEqual(['failed']);
    bridge(async () => ({ opened: false, error: null, reason: 'cancelled' }));
    await openInTerminal('ses_1');
    bridge(async () => ({ opened: true, error: null, reason: 'ok' }));
    await openInTerminal('ses_1');
    expect(toasts).toHaveLength(1);
    bridge(async () => { throw new Error('ipc gone'); });
    await openInTerminal('ses_1');
    expect(toasts).toHaveLength(2);
  });
});
