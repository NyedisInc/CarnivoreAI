
export const E2EE_FRAGMENT_PREFIX = 'v2.';

export const RECORD_VERSION = 0x02;
export const KIND_OPEN = 1;
export const KIND_DATA = 2;
export const KIND_BEAT = 3;
export const KIND_END = 4;
export const KIND_PAINT = 5;

const HEADER_BYTES = 1 + 16 + 8;
const MIN_RECORD_BYTES = HEADER_BYTES + 9 + 16;

export const MAX_FIRST_RECORD_AGE_MS = 10 * 60 * 1000;

export const STALL_AFTER_MS = 15 * 1000;

const INFO_WATCH_AUTH = 'carnivore relay v2 watch-auth';
const INFO_CONTENT_KEY = 'carnivore relay v2 content-key';
const INFO_STREAM_KEY = 'carnivore relay v2 stream-key';
const AAD_PREFIX = 'carnivore-relay-v2';

const encoder = new TextEncoder();

export interface ShareFragment {
    e2ee: boolean;
    token: string;
}

export function parseFragment(hash: string | null | undefined): ShareFragment {
    const raw = (hash ?? '').replace(/^#/, '').trim();
    if (raw.startsWith(E2EE_FRAGMENT_PREFIX)) {
        return { e2ee: true, token: raw.slice(E2EE_FRAGMENT_PREFIX.length) };
    }
    return { e2ee: false, token: raw };
}

export function b64urlDecode(text: string): Uint8Array | null {
    if (!/^[A-Za-z0-9_-]*$/.test(text) || text.length % 4 === 1) return null;
    const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
    let binary: string;
    try {
        binary = atob(padded);
    } catch {
        return null;
    }
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return b64urlEncode(bytes) === text ? bytes : null;
}

export function b64urlEncode(bytes: Uint8Array): string {
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export interface ViewerKeys {
    watchAuth: string;
    contentKey: CryptoKey;
}

export async function deriveViewerKeys(
    token: string,
    linkId: string,
    subtle: SubtleCrypto,
): Promise<ViewerKeys | null> {
    const ikm = b64urlDecode(token);
    if (!ikm || ikm.length !== 32) return null;
    const base = await subtle.importKey('raw', ikm as BufferSource, 'HKDF', false, ['deriveBits']);
    const salt = encoder.encode(linkId);
    const derive = (info: string) =>
        subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info: encoder.encode(info) }, base, 256);
    const watchAuth = new Uint8Array(await derive(INFO_WATCH_AUTH));
    const contentBits = new Uint8Array(await derive(INFO_CONTENT_KEY));
    const contentKey = await subtle.importKey('raw', contentBits, 'HKDF', false, ['deriveKey']);
    contentBits.fill(0);
    ikm.fill(0);
    return { watchAuth: b64urlEncode(watchAuth), contentKey };
}

export function recordAad(linkId: string, streamId: Uint8Array, seq: bigint): Uint8Array {
    const lid = encoder.encode(linkId);
    const prefix = encoder.encode(AAD_PREFIX);
    const out = new Uint8Array(prefix.length + 1 + lid.length + 1 + 16 + 8);
    out.set(prefix, 0);
    let at = prefix.length;
    out[at++] = lid.length;
    out.set(lid, at);
    at += lid.length;
    out[at++] = RECORD_VERSION;
    out.set(streamId, at);
    at += 16;
    new DataView(out.buffer).setBigUint64(at, seq);
    return out;
}

export type IntegrityReason =
    | 'malformed'
    | 'version'
    | 'gap'
    | 'replay'
    | 'tamper'
    | 'kind'
    | 'stale'
    | 'expired'
    | 'open';

export interface RecordEvents {
    grid(cols: number, rows: number): void;
    bytes(data: Uint8Array): void;
    record(): void;
    expiry(atMs: number): void;
    end(): void;
    integrity(reason: IntegrityReason): void;
}

export interface PageStreamState {
    newestOpenMs: number;
    streams: Map<string, bigint>;
}

export function newPageStreams(): PageStreamState {
    return { newestOpenMs: 0, streams: new Map() };
}

export interface RecordReaderOptions {
    linkId: string;
    contentKey: CryptoKey;
    subtle: SubtleCrypto;
    page: PageStreamState;
    events: RecordEvents;
    now?: () => number;
}

export function createRecordReader(options: RecordReaderOptions): {
    push(frame: Uint8Array): void;
    settled(): Promise<void>;
} {
    const { linkId, contentKey, subtle, page, events } = options;
    const now = options.now ?? (() => Date.now());
    let current: string | null = null;
    let currentKey: CryptoKey | null = null;
    let expected = 0n;
    let enteredFirst = false;
    let followed = false;
    let failed = false;
    let chain: Promise<void> = Promise.resolve();

    class Refused extends Error {
        constructor(readonly reason: IntegrityReason) {
            super(reason);
        }
    }

    async function streamKey(streamId: Uint8Array): Promise<CryptoKey> {
        return subtle.deriveKey(
            { name: 'HKDF', hash: 'SHA-256', salt: streamId as BufferSource, info: encoder.encode(INFO_STREAM_KEY) },
            contentKey,
            { name: 'AES-GCM', length: 256 },
            false,
            ['decrypt'],
        );
    }

    async function handle(frame: Uint8Array): Promise<void> {
        if (frame.length < MIN_RECORD_BYTES) throw new Refused('malformed');
        if (frame[0] !== RECORD_VERSION) throw new Refused('version');
        const streamId = frame.slice(1, 17);
        const streamHex = Array.from(streamId, (b) => b.toString(16).padStart(2, '0')).join('');
        const seq = new DataView(frame.buffer, frame.byteOffset + 17, 8).getBigUint64(0);
        const fresh = streamHex !== current;
        const known = page.streams.get(streamHex);
        if (fresh) {
            if (seq !== 0n) throw new Refused('gap');
            if (known !== undefined && current !== null) throw new Refused('replay');
        } else if (seq !== expected) {
            throw new Refused(seq < expected ? 'replay' : 'gap');
        }
        const key = fresh ? await streamKey(streamId) : (currentKey as CryptoKey);
        const nonce = new Uint8Array(12);
        new DataView(nonce.buffer).setBigUint64(4, seq);
        let plain: Uint8Array;
        try {
            plain = new Uint8Array(
                await subtle.decrypt(
                    { name: 'AES-GCM', iv: nonce, additionalData: recordAad(linkId, streamId, seq) as BufferSource, tagLength: 128 },
                    key,
                    frame.slice(HEADER_BYTES) as BufferSource,
                ),
            );
        } catch {
            throw new Refused('tamper');
        }
        if (plain.length < 9) throw new Refused('malformed');
        const kind = plain[0];
        const ts = Number(new DataView(plain.buffer, plain.byteOffset + 1, 8).getBigUint64(0));
        const body = plain.slice(9);
        if ((seq === 0n) !== (kind === KIND_OPEN)) throw new Refused('kind');
        if (kind === KIND_OPEN) {
            const grid = readOpen(body);
            if (grid === null) throw new Refused('open');
            if (grid.expiresAt * 1000 <= now()) throw new Refused('expired');
            if (now() - ts > MAX_FIRST_RECORD_AGE_MS || ts < page.newestOpenMs) {
                throw new Refused('stale');
            }
            if (current !== null && (followed || !enteredFirst) && grid.prev !== null) {
                const last = expected - 1n;
                if (!grid.prev || grid.prev.stream !== current || grid.prev.seq !== last) {
                    throw new Refused('gap');
                }
            }
            page.newestOpenMs = ts;
            enteredFirst = current === null;
            followed = false;
            current = streamHex;
            currentKey = key;
            expected = (known ?? 0n) + 1n;
            page.streams.set(streamHex, known ?? 0n);
            events.record();
            events.expiry(grid.expiresAt * 1000);
            events.grid(grid.cols, grid.rows);
            return;
        }
        expected = seq + 1n;
        followed = true;
        page.streams.set(streamHex, seq);
        events.record();
        if (kind === KIND_DATA || kind === KIND_PAINT) events.bytes(body);
        else if (kind === KIND_END) events.end();
        else if (kind !== KIND_BEAT) throw new Refused('kind');
    }

    return {
        push(frame: Uint8Array): void {
            const copy = frame.slice();
            chain = chain.then(async () => {
                if (failed) return;
                try {
                    await handle(copy);
                } catch (err) {
                    failed = true;
                    events.integrity(err instanceof Refused ? err.reason : 'malformed');
                }
            });
        },
        settled: () => chain,
    };
}

function readOpen(
    body: Uint8Array,
): { cols: number; rows: number; expiresAt: number; prev: { stream: string; seq: bigint } | null } | null {
    let parsed: Record<string, unknown>;
    try {
        parsed = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body)) as Record<string, unknown>;
    } catch {
        return null;
    }
    const { cols, rows, expires_at: expiresAt, scrubber_id: scrubber } = parsed;
    const whole = (value: unknown, max: number): value is number =>
        typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= max;
    if (!whole(cols, 1000) || !whole(rows, 500)) return null;
    if (typeof expiresAt !== 'number' || !Number.isInteger(expiresAt)) return null;
    if (typeof scrubber !== 'string' || !/^[0-9a-f]{12}$/.test(scrubber)) return null;
    const raw = parsed.prev;
    let prev: { stream: string; seq: bigint } | null = null;
    if (raw !== null) {
        const entry = raw as { stream?: unknown; seq?: unknown } | undefined;
        if (
            !entry ||
            typeof entry.stream !== 'string' ||
            !/^[0-9a-f]{32}$/.test(entry.stream) ||
            typeof entry.seq !== 'number' ||
            !Number.isSafeInteger(entry.seq) ||
            entry.seq < 0
        ) {
            return null;
        }
        prev = { stream: entry.stream, seq: BigInt(entry.seq) };
    }
    return { cols, rows, expiresAt, prev };
}
