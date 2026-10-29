
import { accessToken, auth, hasRefreshToken, refreshTokens } from '../../opscenter/api/auth.svelte';
import { resolveAfterUnopenedClose } from '../socket-auth-recovery';

export type ServerMessage =
    | { type: 'restarted' }
    | { type: 'meta'; width: number; height: number; dpr: number }
    | { type: 'nav'; url: string; title: string; canGoBack: boolean; canGoForward: boolean; loading: boolean }
    | { type: 'dialog'; kind: string; message: string; defaultPrompt?: string }
    | { type: 'notice'; message: string }
    | { type: 'stopped'; reason: string }
    | { type: 'error'; code: string; message: string };

export type ConnState = 'connecting' | 'open' | 'stopped' | 'gone' | 'refused' | 'signed-out';

export interface BrowserSocketHandlers {
    onFrame(blob: Blob): void;
    onMessage(message: ServerMessage): void;
    onState(state: ConnState, detail?: string): void;
}

export interface BrowserSocket {
    send(message: object): void;
    reopen(): void;
    close(): void;
}

export type SocketFactory = (url: string, protocols: string[]) => WebSocket;

const MAX_BACKOFF_MS = 15000;

export function browserSocketUrl(id: string, loc: Pick<Location, 'protocol' | 'host'> = location): string {
    const scheme = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${scheme}//${loc.host}/ws/browser?browser_id=${encodeURIComponent(id)}`;
}

export function openBrowserSocket(
    id: string,
    handlers: BrowserSocketHandlers,
    factory: SocketFactory = (url, protocols) => new WebSocket(url, protocols),
): BrowserSocket {
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let retriedAuth = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let ending: { state: ConnState; detail: string } | null = null;
    let openedThisAttempt = false;
    let connectGen = 0;

    function connect(): void {
        if (closed) return;
        const token = accessToken();
        if (!token) {
            if (retriedAuth) handlers.onState('signed-out');
            else {
                retriedAuth = true;
                void refreshTokens().then((ok) => (ok && !closed ? connect() : handlers.onState('signed-out')));
            }
            return;
        }
        ending = null;
        openedThisAttempt = false;
        connectGen += 1;
        const myGen = connectGen;
        handlers.onState('connecting');
        const socket = factory(browserSocketUrl(id), ['cloude.jwt.v1', token]);
        socket.binaryType = 'blob';
        ws = socket;
        socket.onopen = () => {
            attempt = 0;
            retriedAuth = false;
            openedThisAttempt = true;
            handlers.onState('open');
        };
        socket.onmessage = (event: MessageEvent) => {
            if (typeof event.data !== 'string') {
                handlers.onFrame(event.data as Blob);
                return;
            }
            let message: ServerMessage;
            try {
                message = JSON.parse(event.data) as ServerMessage;
            } catch (err) {
                console.warn('BrowserSocket: unreadable message dropped', err);
                return;
            }
            if (message.type === 'stopped') ending = { state: 'stopped', detail: message.reason };
            if (message.type === 'error') ending = { state: 'refused', detail: message.message };
            handlers.onMessage(message);
        };
        socket.onclose = (event: CloseEvent) => {
            if (ws !== socket) return;
            ws = null;
            if (closed) return;
            onClosed(event.code, myGen);
        };
    }

    function confirmUnopenedClose(gen: number): void {
        if (!hasRefreshToken()) return;
        void resolveAfterUnopenedClose(refreshTokens, () => auth.state === 'unreachable').then((outcome) => {
            if (closed || gen !== connectGen) return;
            if (outcome !== 'refreshed') {
                retriedAuth = false;
                return;
            }
            if (timer !== undefined) clearTimeout(timer);
            attempt = 0;
            connect();
        });
    }

    function onClosed(code: number, gen: number): void {
        if (ending) {
            handlers.onState(ending.state, ending.detail);
            return;
        }
        if (code === 4404) {
            handlers.onState('gone');
            return;
        }
        if (code === 4401 && !retriedAuth) {
            retriedAuth = true;
            void refreshTokens().then((ok) => (ok ? connect() : handlers.onState('signed-out')));
            return;
        }
        if (code === 4401) {
            handlers.onState('signed-out');
            return;
        }
        if (!openedThisAttempt && !retriedAuth) {
            retriedAuth = true;
            confirmUnopenedClose(gen);
        }
        const wait = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS);
        attempt += 1;
        handlers.onState('connecting');
        timer = setTimeout(connect, wait);
    }

    connect();

    return {
        send(message) {
            if (ws && ws.readyState === 1) ws.send(JSON.stringify(message));
        },
        reopen() {
            if (closed || ws) return;
            if (timer !== undefined) clearTimeout(timer);
            attempt = 0;
            connect();
        },
        close() {
            closed = true;
            if (timer !== undefined) clearTimeout(timer);
            const socket = ws;
            ws = null;
            socket?.close(1000);
        },
    };
}
