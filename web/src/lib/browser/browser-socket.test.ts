/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { browserSocketUrl, openBrowserSocket, type ConnState } from './browser-socket';

class FakeSocket {
    static made: FakeSocket[] = [];
    binaryType = '';
    readyState = 0;
    sent: string[] = [];
    onopen: (() => void) | null = null;
    onmessage: ((e: { data: unknown }) => void) | null = null;
    onclose: ((e: { code: number }) => void) | null = null;
    constructor(
        public url: string,
        public protocols: string[],
    ) {
        FakeSocket.made.push(this);
    }
    send(data: string): void {
        this.sent.push(data);
    }
    close(): void {
        this.readyState = 3;
    }
    open(): void {
        this.readyState = 1;
        this.onopen?.();
    }
    text(message: unknown): void {
        this.onmessage?.({ data: JSON.stringify(message) });
    }
    drop(code: number): void {
        this.readyState = 3;
        this.onclose?.({ code });
    }
}

const factory = (url: string, protocols: string[]) => new FakeSocket(url, protocols) as unknown as WebSocket;

function start() {
    const states: [ConnState, string | undefined][] = [];
    const frames: unknown[] = [];
    const socket = openBrowserSocket(
        '0123456789abcdef',
        { onFrame: (b) => frames.push(b), onMessage: () => {}, onState: (s, d) => states.push([s, d]) },
        factory,
    );
    return { socket, states, frames, last: () => FakeSocket.made[FakeSocket.made.length - 1]! };
}

beforeEach(() => {
    FakeSocket.made = [];
    localStorage.setItem('claude_tunnel_token', 'tok');
    vi.useFakeTimers();
});

afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
});

test('the token rides the subprotocol, never the URL', () => {
    const { last } = start();
    expect(last().protocols).toEqual(['cloude.jwt.v1', 'tok']);
    expect(last().url).toBe(browserSocketUrl('0123456789abcdef'));
    expect(last().url).not.toContain('tok');
});

test('binary is a frame; text is a message; send waits for open', () => {
    const { socket, frames, last } = start();
    socket.send({ type: 'reload' });
    expect(last().sent).toEqual([]);
    last().open();
    socket.send({ type: 'reload' });
    expect(last().sent).toEqual(['{"type":"reload"}']);
    last().onmessage?.({ data: new Blob(['x']) });
    expect(frames.length).toBe(1);
});

test('a stop is reported and NOT reconnected; reopen relaunches', () => {
    const { socket, states, last } = start();
    last().open();
    last().text({ type: 'stopped', reason: 'idle' });
    last().drop(1000);
    vi.advanceTimersByTime(60000);
    expect(FakeSocket.made.length).toBe(1);
    expect(states[states.length - 1]).toEqual(['stopped', 'idle']);
    socket.reopen();
    expect(FakeSocket.made.length).toBe(2);
});

test('4404 is gone; a refused launch carries the server sentence', () => {
    const a = start();
    a.last().drop(4404);
    expect(a.states[a.states.length - 1]).toEqual(['gone', undefined]);
    const b = start();
    b.last().text({ type: 'error', code: 'cap_reached', message: 'at most 4 browsers' });
    b.last().drop(4503);
    expect(b.states[b.states.length - 1]).toEqual(['refused', 'at most 4 browsers']);
    vi.advanceTimersByTime(60000);
    expect(FakeSocket.made.length).toBe(2);
});

test('a close that never opened confirms via refresh and reconnects at once, not after the whole backoff', async () => {
    localStorage.setItem('claude_refresh_token', 'r1');
    const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ access_token: 'fresh', refresh_token: 'r2' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const { last } = start();
    last().drop(1006);
    expect(FakeSocket.made.length, 'the ordinary backoff still schedules a retry synchronously').toBe(1);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(FakeSocket.made.length,
        'the confirm succeeded and reconnected at once, well before the 1s backoff would have fired').toBe(2);
    vi.unstubAllGlobals();
});

test('a dropped connection reconnects with backoff; close stops it', () => {
    const { socket, last } = start();
    last().open();
    last().drop(1006);
    expect(FakeSocket.made.length).toBe(1);
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.made.length).toBe(2);
    last().drop(1006);
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.made.length, 'the second wait is longer').toBe(2);
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.made.length).toBe(3);
    socket.close();
    last().drop(1006);
    vi.advanceTimersByTime(60000);
    expect(FakeSocket.made.length).toBe(3);
});
