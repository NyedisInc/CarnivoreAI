/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';

import { STATUS_KEY_FLAG, deliverStatusKey, type Fetcher } from './status-key';

type Win = { carnivoreShell?: unknown; webkit?: unknown };
const w = globalThis as unknown as Win;
let sent: unknown[];

beforeEach(() => {
    sent = [];
    localStorage.clear();
    delete w.carnivoreShell;
    delete w.webkit;
});

function fakeShell(): void {
    w.carnivoreShell = { version: 1, platform: 'ios' };
    w.webkit = { messageHandlers: { carnivore: { postMessage: (m: unknown) => sent.push(m) } } };
}

describe('deliverStatusKey', () => {
    test('a plain browser never asks the computer', async () => {
        const fetcher = vi.fn();
        expect(await deliverStatusKey(fetcher as unknown as Fetcher)).toBe(false);
        expect(fetcher).not.toHaveBeenCalled();
    });
    test('the shell gets the token once', async () => {
        fakeShell();
        const fetcher = vi.fn(async () => ({ token: 'T'.repeat(32) })) as unknown as Fetcher;
        expect(await deliverStatusKey(fetcher)).toBe(true);
        expect(sent).toEqual([{ v: 1, type: 'statusKey', token: 'T'.repeat(32) }]);
        expect(localStorage.getItem(STATUS_KEY_FLAG)).toBe('1');
        expect(await deliverStatusKey(fetcher)).toBe(false);
        expect(fetcher).toHaveBeenCalledTimes(1);
    });
    test('a refusal delivers nothing and tries again next boot', async () => {
        fakeShell();
        const fetcher = vi.fn(async () => {
            throw new Error('404');
        }) as unknown as Fetcher;
        expect(await deliverStatusKey(fetcher)).toBe(false);
        expect(sent).toEqual([]);
        expect(localStorage.getItem(STATUS_KEY_FLAG)).toBeNull();
    });
});
