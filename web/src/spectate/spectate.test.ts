/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { webcrypto } from 'node:crypto';

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import SpectatePage from './SpectatePage.svelte';
import { createViewerSocket } from '../opscenter/lib/viewer-socket';
import {
    RELAY_WATCH_SUBPROTOCOL,
    isOver,
    relayLinkId,
    spectateSocketUrl,
    stateForClose,
} from './spectate-socket';
import { isSpectatePath } from './mount';
import { parseFragment } from './e2ee';
import { MAX_FONT_PX, MIN_FONT_PX, fitFontSize } from './fit-font';

const terminals: Array<{
    options: Record<string, unknown>;
    opens: number;
    disposed: number;
    writes: unknown[];
    resizes: Array<[number, number]>;
}> = [];

const sockets: Array<FakeSocket> = [];

class FakeSocket {
    binaryType = '';
    url: string;
    protocols: string[];
    sent: unknown[] = [];
    closes: Array<number | undefined> = [];
    onopen: ((event: unknown) => void) | null = null;
    onmessage: ((event: { data: unknown }) => void) | null = null;
    onclose: ((event: { code: number }) => void) | null = null;
    onerror: ((event: unknown) => void) | null = null;
    private listeners: Array<(event: { code: number }) => void> = [];
    private openListeners: Array<() => void> = [];

    constructor(url: string, protocols: string[]) {
        this.url = url;
        this.protocols = protocols;
        sockets.push(this);
    }

    addEventListener(kind: string, fn: (event: { code: number }) => void): void {
        if (kind === 'close') this.listeners.push(fn);
        if (kind === 'open') this.openListeners.push(fn as unknown as () => void);
    }

    send(data: unknown): void {
        this.sent.push(data);
    }

    close(code?: number): void {
        this.closes.push(code);
    }

    emitClose(code: number): void {
        for (const fn of this.listeners) fn({ code });
        this.onclose?.({ code });
    }

    emitOpen(): void {
        for (const fn of this.openListeners) fn();
        this.onopen?.({});
    }
}

const timers: Array<() => void> = [];
const delays: Array<number | undefined> = [];

function testDeps() {
    return {
        backoffMs: () => 1000,
        requestFrame: (fn: () => void) => {
            fn();
            return 1;
        },
        cancelFrame: () => undefined,
        setTimer: (fn: () => void, ms?: number) => {
            delays.push(ms);
            return timers.push(fn);
        },
        clearTimer: () => undefined,
        queue: {
            MAX_QUEUED_BYTES: 4 * 1024 * 1024,
            dropMarker: () => '',
            overflowBytes: () => 0,
            shedFront: () => 0,
        },
    };
}

function fireTimers(): number {
    const due = timers.splice(0, timers.length);
    delays.length = 0;
    for (const fn of due) fn();
    return due.length;
}

function socketAt(index: number): FakeSocket {
    const socket = sockets[index];
    if (!socket) throw new Error(`the page opened no socket at index ${index}`);
    return socket;
}

function termAt(index: number) {
    const term = terminals[index];
    if (!term) throw new Error(`the page built no emulator at index ${index}`);
    return term;
}

function relayHostFor(hash: string, linkId = 'lnk_1') {
    return {
        WebSocket: FakeSocket as unknown as typeof WebSocket,
        location: { protocol: 'https:', host: 'relay.test', hash, pathname: `/s/${linkId}` },
    };
}

function mountPage(hash: string, host: object = relayHostFor(hash), extra: object = {}) {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const instance = mount(SpectatePage as never, {
        target,
        props: { host, deps: { ...testDeps(), ...extra } } as never,
    });
    flushSync();
    return { instance, target };
}

function sendSize(index: number, cols = 170, rows = 50): void {
    socketAt(index).onmessage?.({ data: JSON.stringify({ type: 'terminal_size', cols, rows }) });
    flushSync();
}

function noticeOf(target: HTMLElement): string {
    return target.querySelector('.spectate-notice')?.textContent?.trim() ?? '';
}

function stateOf(target: HTMLElement): string {
    return (
        target.querySelector('.spectate-notice')?.getAttribute('data-spectate-state') ?? ''
    );
}

beforeEach(() => {
    terminals.length = 0;
    sockets.length = 0;
    timers.length = 0;
    delays.length = 0;
    (globalThis as Record<string, unknown>).Terminal = class {
        private entry = {
            options: {} as Record<string, unknown>,
            opens: 0,
            disposed: 0,
            writes: [] as unknown[],
            resizes: [] as Array<[number, number]>,
        };

        options: Record<string, unknown>;

        constructor(options: Record<string, unknown>) {
            this.entry.options = { ...options };
            this.options = this.entry.options;
            terminals.push(this.entry);
        }

        open(host: HTMLElement): void {
            this.entry.opens += 1;
            const element = document.createElement('div');
            element.className = 'xterm';
            host.appendChild(element);
        }

        resize(cols: number, rows: number): void {
            this.entry.resizes.push([cols, rows]);
        }
        write(data: unknown): void {
            this.entry.writes.push(data);
        }
        dispose(): void {
            this.entry.disposed += 1;
        }
    };
});

afterEach(() => {
    delete (globalThis as Record<string, unknown>).Terminal;
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('the fragment, the url and the close codes', () => {
    test('the token is everything after the hash, and absence is empty', () => {
        expect(parseFragment('#abc123')).toEqual({ e2ee: false, token: 'abc123' });
        expect(parseFragment('abc123')).toEqual({ e2ee: false, token: 'abc123' });
        expect(parseFragment('')).toEqual({ e2ee: false, token: '' });
        expect(parseFragment(undefined)).toEqual({ e2ee: false, token: '' });
    });

    test('the socket url is same origin, scheme matched, and unscoped', () => {
        expect(
            spectateSocketUrl({ protocol: 'https:', host: 'h:8443', pathname: '/s/a' }),
        ).toBe('wss://h:8443/watch/a');
        expect(
            spectateSocketUrl({ protocol: 'http:', host: 'h:8000', pathname: '/s/a' }),
        ).toBe('ws://h:8000/watch/a');
    });

    test('there is no local socket: a path that is not the relay\'s has no url', () => {
        expect(() =>
            spectateSocketUrl({ protocol: 'http:', host: 'mac.local:8000', pathname: '/spectate' }),
        ).toThrow();
        expect(() => spectateSocketUrl({ protocol: 'http:', host: 'mac.local:8000' })).toThrow();
    });

    test('4410 and 4401 are told apart, and nothing else ends an OPEN socket', () => {
        expect(stateForClose(4410, true)).toBe('ended');
        expect(stateForClose(4401, true)).toBe('refused');
        expect(stateForClose(1006, true)).toBe('reconnecting');
        expect(stateForClose(4429, true)).toBe('reconnecting');
        expect(stateForClose(undefined, true)).toBe('reconnecting');
    });

    test('a socket that NEVER OPENED was refused, whatever code came back', () => {
        expect(stateForClose(1006, false)).toBe('refused');
        expect(stateForClose(undefined, false)).toBe('refused');
        expect(stateForClose(4410, false)).toBe('ended');
        expect(stateForClose(1006, true)).toBe('reconnecting');
    });

    test('the three endings are the ones nothing reopens', () => {
        expect(isOver('ended')).toBe(true);
        expect(isOver('refused')).toBe(true);
        expect(isOver('missing')).toBe(true);
        expect(isOver('reconnecting')).toBe(false);
        expect(isOver('connecting')).toBe(false);
        expect(isOver('live')).toBe(false);
    });

    test('only the relay path is a spectator page; the Mac has none', () => {
        expect(isSpectatePath('/s/abc')).toBe(true);
        expect(isSpectatePath('/spectate')).toBe(false);
        expect(isSpectatePath('/spectate/')).toBe(false);
        expect(isSpectatePath('/')).toBe(false);
        expect(isSpectatePath(undefined)).toBe(false);
    });
});

describe('the mounted page', () => {
    test('it opens one spectator socket and asks the network for nothing else', () => {
        const fetchSpy = vi.fn();
        (globalThis as Record<string, unknown>).fetch = fetchSpy;

        const { instance, target } = mountPage('#share-token-value');

        expect(sockets).toHaveLength(1);
        expect(socketAt(0).url).toBe('wss://relay.test/watch/lnk_1');
        expect(socketAt(0).protocols).toEqual([
            RELAY_WATCH_SUBPROTOCOL,
            'share-token-value',
        ]);
        expect(fetchSpy).not.toHaveBeenCalled();
        socketAt(0).emitOpen();
        sendSize(0);
        expect(target.querySelector('.xterm')).not.toBeNull();

        unmount(instance, { outro: false });
    });

    test('the emulator is built with stdin off and no session named', () => {
        const { instance } = mountPage('#tok');
        socketAt(0).emitOpen();
        sendSize(0);

        expect(terminals).toHaveLength(1);
        expect(termAt(0).options.disableStdin).toBe(true);
        expect(termAt(0).options.cursorBlink).toBe(false);
        expect(termAt(0).opens).toBe(1);

        unmount(instance, { outro: false });
    });

    test('a 4401 renders the expired notice, retries nothing, shows no screen', () => {
        const { instance, target } = mountPage('#tok');
        socketAt(0).emitOpen();
        sendSize(0);

        socketAt(0).emitClose(4401);
        flushSync();

        expect(stateOf(target)).toBe('refused');
        expect(noticeOf(target)).toBe('this link has expired or is not valid');
        expect(target.querySelector('.xterm')).toBe(null);
        expect(termAt(0).disposed).toBe(1);

        fireTimers();
        expect(sockets).toHaveLength(1);

        unmount(instance, { outro: false });
    });

    test('A REFUSED HANDSHAKE ARRIVES AS 1006, and is terminal after the first-connect retries', () => {
        const { instance, target } = mountPage('#tok');

        const waits: Array<number | undefined> = [];
        for (let attempt = 0; attempt < 4; attempt += 1) {
            socketAt(attempt).emitClose(1006);
            flushSync();
            expect(stateOf(target)).toBe('connecting');
            waits.push(delays.find((ms) => ms !== undefined && ms >= 1000));
            fireTimers();
            flushSync();
            expect(sockets).toHaveLength(attempt + 2);
        }
        expect(waits).toEqual([1000, 2000, 4000, 8000]);

        socketAt(4).emitClose(1006);
        flushSync();
        expect(stateOf(target)).toBe('refused');
        expect(noticeOf(target)).toBe('this link has expired or is not valid');
        expect(target.querySelector('.xterm')).toBe(null);
        fireTimers();
        expect(sockets).toHaveLength(5);

        unmount(instance, { outro: false });
    });

    test('a link refused at first and then declared is watched, and later refusals are final', () => {
        const { instance, target } = mountPage('#tok');
        socketAt(0).emitClose(1006);
        flushSync();
        fireTimers();
        flushSync();
        socketAt(1).emitOpen();
        sendSize(1);
        flushSync();
        expect(noticeOf(target)).toBe('');
        expect(target.querySelector('.xterm')).not.toBe(null);

        socketAt(1).emitClose(4401);
        flushSync();
        expect(stateOf(target)).toBe('refused');
        fireTimers();
        expect(sockets).toHaveLength(2);

        unmount(instance, { outro: false });
    });

    test('unmounting during a first-connect wait cancels the retry', () => {
        const cleared: unknown[] = [];
        const { instance } = (() => {
            const target = document.createElement('div');
            document.body.appendChild(target);
            const deps = { ...testDeps(), clearTimer: (handle: unknown) => cleared.push(handle) };
            const mounted = mount(SpectatePage as never, {
                target,
                props: { host: relayHostFor('#tok'), deps } as never,
            });
            flushSync();
            return { instance: mounted };
        })();
        socketAt(0).emitClose(1006);
        flushSync();
        unmount(instance, { outro: false });
        fireTimers();
        expect(sockets).toHaveLength(1);
        expect(cleared.length).toBeGreaterThan(0);
    });

    test('a 4410 says the share ended and retries nothing', () => {
        const { instance, target } = mountPage('#tok');
        socketAt(0).emitOpen();
        flushSync();

        socketAt(0).emitClose(4410);
        flushSync();

        expect(stateOf(target)).toBe('ended');
        expect(noticeOf(target)).toBe('this share has ended');
        expect(target.querySelector('.xterm')).toBe(null);
        fireTimers();
        expect(sockets).toHaveLength(1);

        unmount(instance, { outro: false });
    });

    test('A DROPPED LINK DOES RECONNECT, which is what the two above prove', () => {
        const { instance, target } = mountPage('#tok');
        socketAt(0).emitOpen();
        sendSize(0);

        socketAt(0).emitClose(1006);
        flushSync();

        expect(stateOf(target)).toBe('reconnecting');
        expect(target.querySelector('.xterm')).not.toBe(null);

        fireTimers();
        expect(sockets.length).toBeGreaterThan(1);

        unmount(instance, { outro: false });
    });

    test('a page opened with no fragment says so and opens no socket', () => {
        const { instance, target } = mountPage('');

        expect(sockets).toHaveLength(0);
        expect(stateOf(target)).toBe('missing');
        expect(noticeOf(target)).toContain('full share link');
        expect(target.querySelector('.xterm')).toBe(null);

        unmount(instance, { outro: false });
    });

    test('unmounting closes the socket and disposes the emulator', () => {
        // nobody is looking at
        const { instance } = mountPage('#tok');
        socketAt(0).emitOpen();
        sendSize(0);
        expect(socketAt(0).closes).toEqual([]);

        unmount(instance, { outro: false });
        flushSync();

        expect(socketAt(0).closes.length).toBe(1);
        expect(termAt(0).disposed).toBe(1);
    });
});

describe('the read-only claim the page rests on', () => {
    test('a view opened as not interactive refuses to send', () => {
        const term = { resize: () => {}, write: () => {}, dispose: () => {} };
        const opened: FakeSocket[] = [];
        const view = createViewerSocket({
            sessionId: '',
            term,
            interactive: false,
            deps: {
                ...testDeps(),
                openSocket: () => {
                    const socket = new FakeSocket('ws://x/ws/terminal', []);
                    opened.push(socket);
                    return socket as never;
                },
            },
        });
        view.start();
        opened[0]?.onopen?.({});

        const ticket = view.claimInput();
        expect(view.interactive).toBe(false);
        expect(opened).toHaveLength(1);
        expect(view.send('rm -rf /\r', ticket)).toBe(false);
        expect(opened[0]?.sent).toEqual([]);

        view.destroy();
    });
});

describe('the same page, served by the relay at /s/<link_id>', () => {
    test('the relay path is matched exactly and yields the link id', () => {
        expect(relayLinkId('/s/abc_DEF-9')).toBe('abc_DEF-9');
        expect(relayLinkId('/s/abc/')).toBe('abc');
        expect(relayLinkId('/s/')).toBe(null);
        expect(relayLinkId('/s/a/b')).toBe(null);
        expect(relayLinkId('/s/..')).toBe(null);
        expect(relayLinkId('/s/a.b')).toBe(null);
        expect(relayLinkId(`/s/${'x'.repeat(129)}`)).toBe(null);
        expect(relayLinkId('/spectate')).toBe(null);
        expect(isSpectatePath('/s/abc')).toBe(true);
        expect(isSpectatePath('/s/a/b')).toBe(false);
    });

    test('on the relay the socket is /watch/<link_id>, never /ws/terminal', () => {
        expect(
            spectateSocketUrl({ protocol: 'https:', host: 'relay.test', pathname: '/s/lnk_1' }),
        ).toBe('wss://relay.test/watch/lnk_1');
    });

    test('it presents the token ONLY as the relay subprotocol, never in the url', () => {
        const fetchSpy = vi.fn();
        (globalThis as Record<string, unknown>).fetch = fetchSpy;
        const token = 'relay-share-token-value';
        const { instance } = mountPage(`#${token}`, relayHostFor(`#${token}`));

        expect(sockets).toHaveLength(1);
        expect(socketAt(0).url).toBe('wss://relay.test/watch/lnk_1');
        expect(socketAt(0).url).not.toContain(token);
        expect(socketAt(0).protocols).toEqual([RELAY_WATCH_SUBPROTOCOL, token]);
        expect(fetchSpy).not.toHaveBeenCalled();

        unmount(instance, { outro: false });
    });

    test('output is BINARY and control is TEXT: output can never be read as control', () => {
        const { instance } = mountPage('#tok', relayHostFor('#tok'));
        socketAt(0).emitOpen();
        const encoder = new TextEncoder();
        const lookalike = '{"type":"terminal_size","cols":3,"rows":2}';
        socketAt(0).onmessage?.({ data: encoder.encode('early').buffer });
        flushSync();
        expect(terminals).toHaveLength(0);

        sendSize(0, 170, 50);
        socketAt(0).onmessage?.({ data: encoder.encode('xhello').subarray(1) });
        socketAt(0).onmessage?.({ data: encoder.encode(lookalike).buffer });
        socketAt(0).onmessage?.({ data: 'plain text is not output' });
        fireTimers();
        flushSync();

        const decoder = new TextDecoder();
        const written = termAt(0)
            .writes.map((chunk) => decoder.decode(chunk as Uint8Array))
            .join('');
        expect(written).toBe(`hello${lookalike}`);
        expect(termAt(0).resizes).toEqual([]);
        expect([termAt(0).options.cols, termAt(0).options.rows]).toEqual([170, 50]);

        unmount(instance, { outro: false });
    });

    test('nothing is painted before the grid, and each grid is the exact size', () => {
        const { instance, target } = mountPage('#tok', relayHostFor('#tok'));
        socketAt(0).emitOpen();
        flushSync();
        expect(terminals).toHaveLength(0);
        expect(target.querySelector('.xterm')).toBe(null);

        sendSize(0, 170, 50);
        expect(terminals).toHaveLength(1);
        expect([termAt(0).options.cols, termAt(0).options.rows]).toEqual([170, 50]);

        sendSize(0, 90, 30);
        expect(terminals).toHaveLength(1);
        expect(termAt(0).resizes).toEqual([[90, 30]]);

        unmount(instance, { outro: false });
    });

    test('a relay 4410 is the ended screen and a never-opened socket is refused', () => {
        const ended = mountPage('#tok', relayHostFor('#tok'));
        socketAt(0).emitOpen();
        socketAt(0).emitClose(4410);
        flushSync();
        expect(stateOf(ended.target)).toBe('ended');
        fireTimers();
        expect(sockets).toHaveLength(1);
        unmount(ended.instance, { outro: false });

        const refused = mountPage('#tok', relayHostFor('#tok'));
        for (let index = 1; index <= 4; index += 1) {
            socketAt(index).emitClose(1006);
            flushSync();
            expect(stateOf(refused.target)).toBe('connecting');
            fireTimers();
            flushSync();
        }
        socketAt(5).emitClose(1006);
        flushSync();
        expect(stateOf(refused.target)).toBe('refused');
        unmount(refused.instance, { outro: false });
    });
});

describe('the font that fits the pane', () => {
    test('the full width fits, down to the floor, then the stage scrolls', () => {
        expect(fitFontSize(780, 100, 0.6)).toEqual({ fontSize: 13, scroll: false });
        expect(fitFontSize(390, 80, 0.6)).toEqual({ fontSize: 8, scroll: false });
        expect(fitFontSize(390, 170, 0.6)).toEqual({ fontSize: MIN_FONT_PX, scroll: true });
        expect(fitFontSize(4000, 80, 0.6)).toEqual({ fontSize: MAX_FONT_PX, scroll: false });
        const fit = fitFontSize(390, 60, 0.6);
        expect(60 * 0.6 * fit.fontSize).toBeLessThanOrEqual(390);
        expect(fitFontSize(0, 80, 0.6)).toEqual({ fontSize: MAX_FONT_PX, scroll: true });
    });
});

describe('the carnivore chrome around the pane', () => {
    const source = readFileSync(path.resolve(__dirname, 'SpectatePage.svelte'), 'utf8');
    const style = source.slice(source.indexOf('<style>'));

    function rule(selector: string): string {
        const start = style.indexOf(`${selector} {`);
        if (start < 0) throw new Error(`no rule for ${selector}`);
        return style.slice(start, style.indexOf('}', start));
    }

    test('one slim bar carries the wordmark, the state and the read only chip', () => {
        const { instance, target } = mountPage('#tok');
        const bar = target.querySelector('.spectate-bar');
        expect(bar).not.toBeNull();
        const mark = bar?.querySelector('img.spectate-wordmark');
        expect(mark?.getAttribute('src')).toBe('/static/img/carnivore/carnivore-wordmark.png');
        expect(mark?.getAttribute('srcset')).toBe(
            '/static/img/carnivore/carnivore-wordmark@2x.png 2x',
        );
        expect(mark?.getAttribute('alt')).toBe('Carnivore');
        expect(bar?.querySelector('.spectate-badge')?.textContent?.trim()).toBe('read only');
        expect(bar?.querySelector('.spectate-state')).not.toBeNull();
        unmount(instance, { outro: false });
    });

    test('the footer links to carnivore.ai and adds no script or remote asset', () => {
        const { instance, target } = mountPage('#tok');
        const link = target.querySelector('.spectate-footer a');
        expect(link?.getAttribute('href')).toBe('https://carnivore.ai/');
        expect(link?.getAttribute('rel')).toBe('noopener');
        expect(link?.getAttribute('target')).toBe('_blank');
        expect(target.querySelector('.spectate-footer')?.textContent).toBe(
            'shared with carnivore. get it free at carnivore.ai',
        );
        expect(target.querySelector('script, link[rel=stylesheet]')).toBeNull();
        for (const el of target.querySelectorAll('[src], [srcset]')) {
            expect(el.getAttribute('src') ?? '').toMatch(/^\/static\//);
        }
        unmount(instance, { outro: false });
    });

    test('the bar is at most 36px and the stage takes every remaining pixel', () => {
        const { instance, target } = mountPage('#tok');
        const page = target.querySelector('.spectate');
        expect([...(page?.children ?? [])].map((el) => el.className.split(' ')[0])).toEqual([
            'spectate-bar',
            'spectate-body',
            'spectate-footer',
        ]);
        expect(target.querySelector('.spectate-body')?.children).toHaveLength(1);
        expect(target.querySelector('.spectate-body > .spectate-stage')).not.toBeNull();
        expect(rule('.spectate')).toContain('height: 100dvh');
        for (const height of style.matchAll(/\.spectate-bar \{[^}]*height: (\d+)px/g)) {
            expect(Number(height[1])).toBeLessThanOrEqual(36);
        }
        expect(rule('.spectate-body')).toContain('flex: 1');
        expect(rule('.spectate-stage')).toContain('flex: 1');
        expect(rule('.spectate-stage')).toContain('min-height: 0');
        unmount(instance, { outro: false });
    });

    test('the carnivore default palette paints the chrome and the emulator', () => {
        const { instance, target } = mountPage('#tok');
        const page = target.querySelector('.spectate') as HTMLElement;
        expect(page.getAttribute('data-session-theme')).toBe('carnivore');
        expect(page.style.getPropertyValue('--color-bg-page').trim()).toBe('#02161e');
        expect(page.style.getPropertyValue('--color-accent').trim()).toBe('#ff6268');
        expect(style).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
        socketAt(0).emitOpen();
        sendSize(0);
        const theme = termAt(0).options.theme as Record<string, string>;
        expect(theme.background).toBe('#02161e');
        expect(theme.foreground).toBe('#eaebed');
        unmount(instance, { outro: false });
    });

    test('the state indicator names every state and the dot follows it', () => {
        const { instance, target } = mountPage('#tok');
        const state = () => target.querySelector('.spectate-state');
        expect(state()?.getAttribute('data-spectate-state')).toBe('connecting');
        expect(state()?.textContent?.trim()).toBe('connecting');
        socketAt(0).emitOpen();
        sendSize(0);
        expect(state()?.getAttribute('data-spectate-state')).toBe('live');
        expect(state()?.textContent?.trim()).toBe('live');
        socketAt(0).emitClose(4410);
        flushSync();
        expect(state()?.getAttribute('data-spectate-state')).toBe('ended');
        expect(state()?.textContent?.trim()).toBe('');
        expect(target.querySelector('.spectate-ending')?.textContent?.trim()).toBe(
            'this share has ended',
        );
        unmount(instance, { outro: false });

        const refused = mountPage('#tok');
        socketAt(1).emitOpen();
        sendSize(1);
        socketAt(1).emitClose(4401);
        flushSync();
        expect(
            refused.target.querySelector('.spectate-state')?.getAttribute('data-spectate-state'),
        ).toBe('refused');
        unmount(refused.instance, { outro: false });
    });
});

describe('an end-to-end encrypted share (v2)', () => {
    const VECTORS = JSON.parse(
        readFileSync(path.resolve(__dirname, '../../../tests/fixtures/relay_e2ee_vectors.json'), 'utf8'),
    ) as {
        token: string;
        link_id: string;
        watch_auth_b64url: string;
        records: Array<{ ts_ms: number; body_hex: string; record_hex: string }>;
    };
    const unhex = (text: string) => Uint8Array.from(text.match(/../g) ?? [], (h) => parseInt(h, 16));
    const records = VECTORS.records.map((r) => unhex(r.record_hex));
    const e2eeDeps = { subtle: webcrypto.subtle, now: () => VECTORS.records[0]!.ts_ms + 1000 };
    const hash = `#v2.${VECTORS.token}`;

    async function mountV2(fragment = hash) {
        const page = mountPage(fragment, relayHostFor(fragment, VECTORS.link_id), e2eeDeps);
        await vi.waitFor(() => {
            if (sockets.length === 0 && !page.target.querySelector('.spectate-ending')) {
                throw new Error('not dialled yet');
            }
        });
        flushSync();
        return page;
    }

    async function deliver(...frames: Uint8Array[]) {
        for (const frame of frames) socketAt(0).onmessage?.({ data: frame.slice().buffer });
        await new Promise((resolve) => setTimeout(resolve, 25));
        flushSync();
    }

    test('it presents A to the relay, never the share token', async () => {
        const { instance } = await mountV2();
        expect(socketAt(0).protocols).toEqual([RELAY_WATCH_SUBPROTOCOL, VECTORS.watch_auth_b64url]);
        expect(JSON.stringify(socketAt(0).protocols)).not.toContain(VECTORS.token);
        expect(socketAt(0).url).toBe(`wss://relay.test/watch/${VECTORS.link_id}`);
        unmount(instance, { outro: false });
    });

    test('it paints the decrypted stream at the OPEN grid and ignores relay text', async () => {
        const { instance } = await mountV2();
        socketAt(0).emitOpen();
        sendSize(0, 3, 2);
        expect(terminals).toHaveLength(0);
        await deliver(records[0]!, records[1]!, records[2]!);
        fireTimers();
        expect(terminals).toHaveLength(1);
        expect([termAt(0).options.cols, termAt(0).options.rows]).toEqual([120, 40]);
        const decoder = new TextDecoder();
        const written = termAt(0).writes.map((c) => decoder.decode(c as Uint8Array)).join('');
        expect(written).toBe(
            decoder.decode(unhex(VECTORS.records[1]!.body_hex)) +
                decoder.decode(unhex(VECTORS.records[2]!.body_hex)),
        );
        unmount(instance, { outro: false });
    });

    test('a tampered record ends the page on the integrity screen, not refused or ended', async () => {
        const { instance, target } = await mountV2();
        socketAt(0).emitOpen();
        const bad = records[1]!.slice();
        bad[bad.length - 1]! ^= 1;
        await deliver(records[0]!, bad);
        expect(stateOf(target)).toBe('integrity');
        expect(noticeOf(target)).toContain('integrity check');
        expect(target.querySelector('.xterm')).toBe(null);
        expect(socketAt(0).closes.length).toBeGreaterThan(0);
        fireTimers();
        expect(sockets).toHaveLength(1);
        unmount(instance, { outro: false });
    });

    test('an authenticated END is the ended screen', async () => {
        const { instance, target } = await mountV2();
        socketAt(0).emitOpen();
        await deliver(...records);
        expect(stateOf(target)).toBe('ended');
        unmount(instance, { outro: false });
    });

    test('a token of the wrong length never dials and says the link is not valid', async () => {
        const { instance, target } = await mountV2('#v2.AAAA');
        expect(sockets).toHaveLength(0);
        expect(stateOf(target)).toBe('refused');
        unmount(instance, { outro: false });
    });

    test('fifteen seconds without a record shows stalled, and a record clears it', async () => {
        const { instance, target } = await mountV2();
        socketAt(0).emitOpen();
        await deliver(records[0]!, records[1]!);
        fireTimers();
        flushSync();
        expect(target.querySelector('[data-spectate-stalled]')?.textContent?.trim()).toBe('stalled');
        await deliver(records[2]!);
        expect(target.querySelector('[data-spectate-stalled]')).toBe(null);
        unmount(instance, { outro: false });
    });
});

