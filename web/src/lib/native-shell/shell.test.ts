/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { enableNativeAlerts } from './native-alerts';
import { bootNativeShell, inNativeShell, isSafePath, parseFromNative, postToNative } from './shell';
import type { Fetcher } from './native-alerts';

type Win = { carnivoreShell?: unknown; webkit?: unknown };
const w = globalThis as unknown as Win;
let sent: unknown[];

function fakeShell(version: unknown = 1): void {
    sent = [];
    w.carnivoreShell = { version, platform: 'ios' };
    w.webkit = { messageHandlers: { carnivore: { postMessage: (m: unknown) => sent.push(m) } } };
}

beforeEach(() => {
    delete w.carnivoreShell;
    delete w.webkit;
    document.documentElement.dataset.theme = 'dracula';
});
afterEach(() => vi.useRealTimers());

describe('detection', () => {
    test('a plain browser is not a shell and sends nothing', () => {
        expect(inNativeShell()).toBe(false);
        expect(postToNative({ type: 'ready' })).toBe(false);
        expect(bootNativeShell()).toBe(false);
    });
    test('needs the handler and a known version', () => {
        w.carnivoreShell = { version: 1 };
        expect(inNativeShell()).toBe(false);
        fakeShell(2);
        expect(inNativeShell()).toBe(false);
        fakeShell(1);
        expect(inNativeShell()).toBe(true);
    });
});

describe('messages', () => {
    test('boot sends ready then the theme, and the theme again when it changes', async () => {
        fakeShell();
        expect(bootNativeShell()).toBe(true);
        expect(sent).toEqual([
            { v: 1, type: 'ready' },
            { v: 1, type: 'theme', id: 'dracula' },
        ]);
        document.documentElement.dataset.theme = 'nord';
        await Promise.resolve();
        expect(sent.at(-1)).toEqual({ v: 1, type: 'theme', id: 'nord' });
    });
    test('native messages are validated', () => {
        const token = { v: 1, type: 'pushToken', token: 'ab12', environment: 'sandbox', payload_key: 'k', bundle_id: 'ai.carnivore.ios', app_version: '1' };
        expect(parseFromNative(token)).toMatchObject({ type: 'pushToken' });
        expect(parseFromNative({ ...token, v: 2 })).toBeNull();
        expect(parseFromNative({ ...token, payload_key: '' })).toBeNull();
        expect(parseFromNative({ v: 1, type: 'nope' })).toBeNull();
        expect(parseFromNative({ v: 1, type: 'openPath', path: '/s/1' })).toEqual({ type: 'openPath', path: '/s/1' });
        expect(parseFromNative({ v: 1, type: 'openPath', path: '//evil.test' })).toBeNull();
        expect(isSafePath('https://evil.test')).toBe(false);
        expect(isSafePath('/a\\b')).toBe(false);
    });
});

describe('enableNativeAlerts', () => {
    test('asks the shell, posts the token with the key, and reports the row id back', async () => {
        fakeShell();
        bootNativeShell();
        sent.length = 0;
        const calls: { path: string; body: unknown }[] = [];
        const fetcher = (async (path: string, init?: RequestInit) => {
            calls.push({ path, body: JSON.parse(String(init?.body)) });
            return { id: 'nd1' };
        }) as unknown as Fetcher;
        const done = enableNativeAlerts(fetcher, 1000);
        expect(sent).toEqual([{ v: 1, type: 'registerPush' }]);
        (w.carnivoreShell as { receive: (m: unknown) => void }).receive({
            v: 1, type: 'pushToken', token: 'ab12', environment: 'production', payload_key: 'key32', bundle_id: 'ai.carnivore.ios', app_version: '1.0',
        });
        await expect(done).resolves.toBe('nd1');
        expect(calls).toEqual([
            { path: '/native-devices', body: { platform: 'ios', token: 'ab12', environment: 'production', bundle_id: 'ai.carnivore.ios', app_version: '1.0', payload_key: 'key32' } },
        ]);
        expect(sent.at(-1)).toEqual({ v: 1, type: 'pushRegistered', id: 'nd1' });
    });
    test('a shell refusal and silence both reject', async () => {
        fakeShell();
        bootNativeShell();
        const refused = enableNativeAlerts((async () => ({})) as unknown as Fetcher, 1000);
        (w.carnivoreShell as { receive: (m: unknown) => void }).receive({ v: 1, type: 'pushFailed', reason: 'denied' });
        await expect(refused).rejects.toThrow('denied');
        vi.useFakeTimers();
        const silent = enableNativeAlerts((async () => ({})) as unknown as Fetcher, 50);
        const check = expect(silent).rejects.toThrow('timeout');
        await vi.advanceTimersByTimeAsync(60);
        await check;
    });
});
