
import type { ViewerSocketLike } from '../opscenter/lib/viewer-socket';

export const RELAY_WATCH_SUBPROTOCOL = 'cloude.relay.watch.v1';

const RELAY_VIEWER_PATH = /^\/s\/([A-Za-z0-9_-]{1,128})\/?$/;

export function relayLinkId(pathname: string | null | undefined): string | null {
    const match = RELAY_VIEWER_PATH.exec(pathname ?? '');
    return match ? (match[1] ?? null) : null;
}

export const CLOSE_SPECTATOR_ENDED = 4410;

export const CLOSE_SPECTATOR_REFUSED = 4401;

export const CLOSE_SPECTATOR_MALFORMED = 4400;

export type SpectateState =
    | 'connecting'
    | 'live'
    | 'reconnecting'
    | 'ended'
    | 'refused'
    | 'integrity'
    | 'missing';

export function spectateSocketUrl(
    location: { protocol: string; host: string; pathname?: string },
): string {
    const linkId = relayLinkId(location.pathname);
    if (linkId === null) throw new Error('not a relay viewer path');
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${scheme}//${location.host}/watch/${linkId}`;
}

function relayFrames(socket: WebSocket, sealed?: SealedChannel): ViewerSocketLike {
    const view: ViewerSocketLike = {
        get binaryType() {
            return socket.binaryType;
        },
        set binaryType(value: string) {
            socket.binaryType = value as BinaryType;
        },
        close: (code?: number, reason?: string) => socket.close(code, reason),
        onopen: null,
        onmessage: null,
        onclose: null,
        onerror: null,
    };
    socket.onopen = (event) => view.onopen?.(event);
    const reader = sealed?.({
        grid: (cols, rows) =>
            view.onmessage?.({ data: JSON.stringify({ type: 'terminal_size', cols, rows }) }),
        bytes: (data) => view.onmessage?.({ data }),
    });
    socket.onmessage = (event) => {
        const data: unknown = event.data;
        if (reader) {
            if (ArrayBuffer.isView(data)) {
                reader.push(new Uint8Array(data.buffer, data.byteOffset, data.byteLength));
            } else if (isBuffer(data)) {
                reader.push(new Uint8Array(data as ArrayBuffer));
            }
            return;
        }
        if (typeof data === 'string') view.onmessage?.({ data });
        else if (ArrayBuffer.isView(data)) {
            view.onmessage?.({
                data: new Uint8Array(data.buffer, data.byteOffset, data.byteLength),
            });
        } else if (isBuffer(data)) {
            view.onmessage?.({ data: new Uint8Array(data as ArrayBuffer) });
        }
    };
    socket.onclose = (event) => view.onclose?.(event);
    socket.onerror = (event) => view.onerror?.(event);
    return view;
}

export interface SealedSink {
    grid(cols: number, rows: number): void;
    bytes(data: Uint8Array): void;
}

export type SealedChannel = (sink: SealedSink) => { push(frame: Uint8Array): void };

function isBuffer(data: unknown): boolean {
    return Object.prototype.toString.call(data) === '[object ArrayBuffer]';
}

export function spectatorOpener(
    token: string,
    win: {
        WebSocket: typeof WebSocket;
        location: { protocol: string; host: string; pathname?: string };
    },
    report: SpectatorSocketReport,
    sealed?: SealedChannel,
): () => ViewerSocketLike {
    return () => {
        const socket = new win.WebSocket(spectateSocketUrl(win.location), [
            RELAY_WATCH_SUBPROTOCOL,
            token,
        ]);
        socket.addEventListener('open', () => {
            report.onOpen();
        });
        socket.addEventListener('close', (event) => {
            report.onClose((event as CloseEvent).code);
        });
        return relayFrames(socket, sealed);
    };
}

export interface SpectatorSocketReport {
    onOpen(): void;
    onClose(code: number | undefined): void;
}

export function stateForClose(
    code: number | undefined,
    opened: boolean,
): SpectateState {
    if (code === CLOSE_SPECTATOR_ENDED) return 'ended';
    if (code === CLOSE_SPECTATOR_REFUSED || code === CLOSE_SPECTATOR_MALFORMED) {
        return 'refused';
    }
    if (!opened) return 'refused';
    return 'reconnecting';
}

export const FIRST_CONNECT_RETRY_MS: readonly number[] = [1000, 2000, 4000, 8000];

export function firstConnectRetryDelay(
    verdict: SpectateState,
    everOpened: boolean,
    attempt: number,
): number | null {
    if (verdict !== 'refused' || everOpened) return null;
    return FIRST_CONNECT_RETRY_MS[attempt] ?? null;
}

export function isOver(state: SpectateState): boolean {
    return state === 'ended' || state === 'refused' || state === 'integrity' || state === 'missing';
}
