import { readFileSync } from 'node:fs';
import path from 'node:path';
import { webcrypto } from 'node:crypto';

import { describe, expect, test } from 'vitest';

import {
    KIND_OPEN,
    MAX_FIRST_RECORD_AGE_MS,
    b64urlDecode,
    b64urlEncode,
    createRecordReader,
    deriveViewerKeys,
    newPageStreams,
    parseFragment,
    recordAad,
    type IntegrityReason,
    type PageStreamState,
} from './e2ee';

const subtle = webcrypto.subtle as unknown as SubtleCrypto;

interface VectorRecord {
    seq: number;
    kind: number;
    ts_ms: number;
    body_hex: string;
    aad_hex: string;
    record_hex: string;
}

const VECTORS = JSON.parse(
    readFileSync(path.resolve(__dirname, '../../../tests/fixtures/relay_e2ee_vectors.json'), 'utf-8'),
) as {
    token: string;
    link_id: string;
    watch_auth_b64url: string;
    verifier_hex: string;
    content_key_hex: string;
    stream_id_hex: string;
    stream_key_hex: string;
    fragment: string;
    wrong_length_tokens: string[];
    records: VectorRecord[];
};

const hex = (bytes: Uint8Array) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
const unhex = (text: string) => Uint8Array.from(text.match(/../g) ?? [], (h) => parseInt(h, 16));
const records = VECTORS.records.map((r) => unhex(r.record_hex));
const TS0 = VECTORS.records[0]!.ts_ms;

async function seal(stream: Uint8Array, seq: bigint, kind: number, ts: number, body: string): Promise<Uint8Array> {
    const k = await subtle.importKey('raw', unhex(VECTORS.content_key_hex), 'HKDF', false, ['deriveKey']);
    const ks = await subtle.deriveKey(
        { name: 'HKDF', hash: 'SHA-256', salt: stream as BufferSource, info: new TextEncoder().encode('carnivore relay v2 stream-key') },
        k,
        { name: 'AES-GCM', length: 256 },
        false,
        ['encrypt'],
    );
    const text = new TextEncoder().encode(body);
    const plain = new Uint8Array(9 + text.length);
    plain[0] = kind;
    new DataView(plain.buffer).setBigUint64(1, BigInt(ts));
    plain.set(text, 9);
    const nonce = new Uint8Array(12);
    new DataView(nonce.buffer).setBigUint64(4, seq);
    const sealed = new Uint8Array(await subtle.encrypt(
        { name: 'AES-GCM', iv: nonce, additionalData: recordAad(VECTORS.link_id, stream, seq) as BufferSource },
        ks,
        plain,
    ));
    const out = new Uint8Array(25 + sealed.length);
    out[0] = 2;
    out.set(stream, 1);
    new DataView(out.buffer).setBigUint64(17, seq);
    out.set(sealed, 25);
    return out;
}

async function reader(now = TS0 + 1000, page: PageStreamState = newPageStreams()) {
    const keys = await deriveViewerKeys(VECTORS.token, VECTORS.link_id, subtle);
    if (!keys) throw new Error('vector token refused');
    const seen = {
        grids: [] as Array<[number, number]>,
        bytes: [] as string[],
        records: 0,
        ended: 0,
        expiries: [] as number[],
        integrity: [] as IntegrityReason[],
    };
    const decoder = new TextDecoder();
    const r = createRecordReader({
        linkId: VECTORS.link_id,
        contentKey: keys.contentKey,
        subtle,
        page,
        now: () => now,
        events: {
            grid: (c, rows) => seen.grids.push([c, rows]),
            bytes: (d) => seen.bytes.push(decoder.decode(d)),
            record: () => (seen.records += 1),
            expiry: (at) => seen.expiries.push(at),
            end: () => (seen.ended += 1),
            integrity: (why) => seen.integrity.push(why),
        },
    });
    const feed = async (...frames: Uint8Array[]) => {
        for (const f of frames) r.push(f);
        await r.settled();
    };
    return { seen, feed };
}

describe('keys', () => {
    test('A, V, the stream key and every AAD match the Mac for the same token', async () => {
        const keys = await deriveViewerKeys(VECTORS.token, VECTORS.link_id, subtle);
        expect(keys?.watchAuth).toBe(VECTORS.watch_auth_b64url);
        const a = b64urlDecode(keys!.watchAuth)!;
        expect(hex(new Uint8Array(await subtle.digest('SHA-256', a as BufferSource)))).toBe(VECTORS.verifier_hex);
        await expect(subtle.exportKey('raw', keys!.contentKey)).rejects.toThrow();
        const rawK = await subtle.importKey('raw', unhex(VECTORS.content_key_hex), 'HKDF', false, ['deriveBits']);
        const ks = await subtle.deriveBits(
            { name: 'HKDF', hash: 'SHA-256', salt: unhex(VECTORS.stream_id_hex), info: new TextEncoder().encode('carnivore relay v2 stream-key') },
            rawK,
            256,
        );
        expect(hex(new Uint8Array(ks))).toBe(VECTORS.stream_key_hex);
        for (const vec of VECTORS.records) {
            expect(hex(recordAad(VECTORS.link_id, unhex(VECTORS.stream_id_hex), BigInt(vec.seq)))).toBe(vec.aad_hex);
        }
    });

    test('a token that is not exactly 32 bytes of base64url derives nothing', async () => {
        for (const bad of [...VECTORS.wrong_length_tokens, `${VECTORS.token}=`, `${VECTORS.token.slice(0, -1)}9`, '', 'no!']) {
            expect(await deriveViewerKeys(bad, VECTORS.link_id, subtle)).toBe(null);
        }
        expect(b64urlEncode(b64urlDecode(VECTORS.token)!)).toBe(VECTORS.token);
    });

    test('the fragment says v2 and carries the token', () => {
        expect(parseFragment(`#${VECTORS.fragment}`)).toEqual({ e2ee: true, token: VECTORS.token });
        expect(parseFragment('#plain')).toEqual({ e2ee: false, token: 'plain' });
        expect(parseFragment('')).toEqual({ e2ee: false, token: '' });
    });
});

describe('the record chain', () => {
    test('the vectors decrypt, in order, to the Mac plaintext', async () => {
        const { seen, feed } = await reader();
        await feed(...records);
        expect(seen.integrity).toEqual([]);
        expect(seen.grids).toEqual([[120, 40]]);
        const decoder = new TextDecoder();
        expect(seen.bytes).toEqual([1, 2].map((i) => decoder.decode(unhex(VECTORS.records[i]!.body_hex))));
        expect(seen.records).toBe(5);
        expect(seen.ended).toBe(1);
    });

    test.each([
        ['ver', 0],
        ['stream id', 5],
        ['seq', 24],
        ['ciphertext', 30],
        ['tag', -1],
    ])('a bit flipped in the %s stops the stream', async (_label, offset) => {
        const { seen, feed } = await reader();
        const bad = records[1]!.slice();
        bad[offset < 0 ? bad.length + offset : offset]! ^= 1;
        await feed(records[0]!, bad, records[2]!);
        expect(seen.integrity).toHaveLength(1);
        expect(seen.bytes).toEqual([]);
    });

    test('a gap, a reorder and a repeat each stop the stream', async () => {
        for (const order of [[0, 2], [0, 2, 1], [0, 1, 1]]) {
            const { seen, feed } = await reader();
            await feed(...order.map((i) => records[i]!));
            expect(seen.integrity).toHaveLength(1);
        }
    });

    test('the first record must be an OPEN', async () => {
        const { seen, feed } = await reader();
        await feed(records[1]!);
        expect(seen.integrity).toEqual(['gap']);
    });

    test('an old stream replayed after a newer one is refused', async () => {
        const page = newPageStreams();
        const { seen, feed } = await reader(TS0 + 1000, page);
        await feed(records[0]!, records[1]!);
        expect(seen.integrity).toEqual([]);
        await feed(records[0]!);
        expect(seen.integrity).toEqual(['replay']);
        page.newestOpenMs = TS0 + 10;
        const again = await reader(TS0 + 1000, page);
        await again.feed(records[0]!);
        expect(again.seen.integrity).toEqual(['stale']);
    });

    test('a stream this socket already left is never returned to', async () => {
        const now = TS0 + 60_000;
        const open = (fill: number, prev: number | null) =>
            seal(new Uint8Array(16).fill(fill), 0n, KIND_OPEN, now - 1000, JSON.stringify({
                client_version: 'x', cols: 80, expires_at: Math.floor(now / 1000) + 600,
                prev: prev === null ? null : { stream: prev.toString(16).padStart(2, '0').repeat(16), seq: 0 },
                rows: 24, scrubber_id: '0123456789ab',
            }));
        const { seen, feed } = await reader(now);
        await feed(await open(1, null), await open(2, 1));
        expect(seen.integrity).toEqual([]);
        await feed(await open(1, 2));
        expect(seen.integrity).toEqual(['replay']);
    });

    describe('stream boundaries (the adversarial review)', () => {
        const T = TS0 + 60_000;
        const hexOf = (fill: number) => fill.toString(16).padStart(2, '0').repeat(16);
        const openRec = (fill: number, prev: [number, number] | null, ts = T) =>
            seal(new Uint8Array(16).fill(fill), 0n, KIND_OPEN, ts, JSON.stringify({
                client_version: 'x', cols: 80, expires_at: Math.floor(T / 1000) + 3600,
                prev: prev && { stream: hexOf(prev[0]), seq: prev[1] }, rows: 24,
                scrubber_id: '0123456789ab',
            }));
        const dataRec = (fill: number, seq: number, text = `d${seq}`) =>
            seal(new Uint8Array(16).fill(fill), BigInt(seq), 2, T, text);

        test('records dropped at a stream boundary are detected', async () => {
            const dropped = await reader(T + 1000);
            await dropped.feed(await openRec(1, null), await dataRec(1, 1), await openRec(2, [1, 2]));
            expect(dropped.seen.integrity).toEqual(['gap']);
            const whole = await reader(T + 1000);
            await whole.feed(await openRec(1, null), await dataRec(1, 1), await dataRec(1, 2),
                await openRec(2, [1, 2]));
            expect(whole.seen.integrity).toEqual([]);
        });

        test('a publisher restart (an OPEN with no prev) resyncs a following viewer', async () => {
            const r = await reader(T + 1000);
            await r.feed(await openRec(1, null), await dataRec(1, 1), await openRec(2, null),
                await dataRec(2, 1));
            expect(r.seen.integrity).toEqual([]);
            expect(r.seen.bytes).toEqual(['d1', 'd1']);
        });

        test('a joiner handed only the cached OPEN may skip to the next stream', async () => {
            const joiner = await reader(T + 1000);
            await joiner.feed(await openRec(1, null), await openRec(2, [1, 7]), await dataRec(2, 1));
            expect(joiner.seen.integrity).toEqual([]);
            expect(joiner.seen.bytes).toEqual(['d1']);
        });

        test('a reconnect never re-applies what the page already applied', async () => {
            const page = newPageStreams();
            const first = await reader(T + 1000, page);
            await first.feed(await openRec(1, null), await dataRec(1, 1), await dataRec(1, 2));
            const replayed = await reader(T + 1000, page);
            await replayed.feed(await openRec(1, null), await dataRec(1, 1));
            expect(replayed.seen.integrity).toEqual(['replay']);
            const resumed = await reader(T + 1000, page);
            await resumed.feed(await openRec(1, null), await dataRec(1, 3));
            expect(resumed.seen.integrity).toEqual([]);
            expect(resumed.seen.bytes).toEqual(['d3']);
        });

        test('every OPEN, not only the first, must be under ten minutes old', async () => {
            let clock = T + 1000;
            const keys = await deriveViewerKeys(VECTORS.token, VECTORS.link_id, subtle);
            const integrity: string[] = [];
            const r = createRecordReader({
                linkId: VECTORS.link_id, contentKey: keys!.contentKey, subtle,
                page: newPageStreams(), now: () => clock,
                events: { grid: () => {}, bytes: () => {}, record: () => {}, expiry: () => {},
                    end: () => {}, integrity: (why) => integrity.push(why) },
            });
            r.push(await openRec(1, null));
            await r.settled();
            clock = T + MAX_FIRST_RECORD_AGE_MS + 5000;
            r.push(await openRec(2, [1, 0], T + 1));
            await r.settled();
            expect(integrity).toEqual(['stale']);
        });

        test('an OPEN reports the share expiry so the page can end itself', async () => {
            const r = await reader(T + 1000);
            await r.feed(await openRec(1, null));
            expect(r.seen.expiries).toEqual([(Math.floor(T / 1000) + 3600) * 1000]);
        });
    });

    test('a first record over ten minutes old is refused', async () => {
        const late = await reader(TS0 + MAX_FIRST_RECORD_AGE_MS + 1);
        await late.feed(records[0]!);
        expect(late.seen.integrity).toEqual(['stale']);
        const fine = await reader(TS0 + MAX_FIRST_RECORD_AGE_MS - 1);
        await fine.feed(records[0]!);
        expect(fine.seen.integrity).toEqual([]);
    });

    test('an OPEN whose share has expired is refused even when it is fresh', async () => {
        const now = TS0 + 60_000;
        const stream = new Uint8Array(16).fill(7);
        const open = (expiresAt: number) =>
            seal(stream, 0n, KIND_OPEN, now - 1000, JSON.stringify({
                client_version: 'x', cols: 80, expires_at: expiresAt, prev: null, rows: 24,
                scrubber_id: '0123456789ab',
            }));
        const expired = await reader(now);
        await expired.feed(await open(Math.floor(now / 1000) - 1));
        expect(expired.seen.integrity).toEqual(['expired']);
        const live = await reader(now);
        await live.feed(await open(Math.floor(now / 1000) + 600));
        expect(live.seen.integrity).toEqual([]);
        expect(live.seen.grids).toEqual([[80, 24]]);
    });
});
