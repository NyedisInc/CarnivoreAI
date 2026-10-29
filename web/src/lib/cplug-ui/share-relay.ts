
export const MAX_SHARE_BYTES = 4096;
export const MAX_SHARE_DEPTH = 8;
export const MAX_SENDS = 10;
export const WINDOW_MS = 1000;

export type ShareError = 'too_large' | 'not_json';

export type Deliver = (value: unknown) => void;

interface Install {
    readonly frames: Map<string, Deliver>;
    last: unknown;
    has: boolean;
    sent: number[];
    from: string | null;
    timer: ReturnType<typeof setTimeout> | null;
}

function depthOf(value: unknown): number {
    if (typeof value !== 'object' || value === null) return 0;
    let deepest = 0;
    for (const child of Object.values(value)) deepest = Math.max(deepest, depthOf(child));
    return deepest + 1;
}

export function cleanShare(value: unknown): { ok: true; value: unknown } | { ok: false; error: ShareError } {
    let text: string | undefined;
    try {
        text = JSON.stringify(value);
    } catch {
        return { ok: false, error: 'not_json' };
    }
    if (text === undefined) return { ok: false, error: 'not_json' };
    if (new TextEncoder().encode(text).length > MAX_SHARE_BYTES) return { ok: false, error: 'too_large' };
    const copy: unknown = JSON.parse(text);
    return depthOf(copy) > MAX_SHARE_DEPTH ? { ok: false, error: 'too_large' } : { ok: true, value: copy };
}

export function createShareRelay(now: () => number = () => Date.now()) {
    const installs = new Map<string, Install>();
    const installOf = (key: string): Install => {
        let found = installs.get(key);
        if (!found) installs.set(key, (found = { frames: new Map(), last: undefined, has: false, sent: [], from: null, timer: null }));
        return found;
    };

    const flush = (install: Install): void => {
        install.timer = null;
        install.sent = install.sent.filter((at) => now() - at < WINDOW_MS);
        install.sent.push(now());
        for (const [id, deliver] of install.frames) if (id !== install.from) deliver(install.last);
    };

    return {
        register(installKey: string, frameId: string, deliver: Deliver): () => void {
            const install = installOf(installKey);
            install.frames.set(frameId, deliver);
            return () => {
                install.frames.delete(frameId);
                if (install.frames.size === 0 && !install.has && installs.get(installKey) === install) installs.delete(installKey);
            };
        },
        replay(installKey: string, frameId: string): void {
            const install = installs.get(installKey);
            if (install?.has) install.frames.get(frameId)?.(install.last);
        },
        share(installKey: string, frameId: string, value: unknown): { ok: true } | { ok: false; error: ShareError } {
            const clean = cleanShare(value);
            if (!clean.ok) return clean;
            const install = installOf(installKey);
            install.last = clean.value;
            install.has = true;
            install.from = frameId;
            if (install.timer !== null) return { ok: true };
            install.sent = install.sent.filter((at) => now() - at < WINDOW_MS);
            if (install.sent.length < MAX_SENDS) {
                flush(install);
            } else {
                const wait = Math.max(0, (install.sent[0] ?? 0) + WINDOW_MS - now());
                install.timer = setTimeout(() => flush(install), wait);
            }
            return { ok: true };
        },
        retain(active: ReadonlySet<string>): void {
            for (const [key, install] of installs) {
                if (active.has(key)) continue;
                if (install.timer !== null) clearTimeout(install.timer);
                install.has = false;
                install.last = undefined;
                install.timer = null;
                if (install.frames.size === 0) installs.delete(key);
            }
        },
        last(installKey: string): unknown {
            const install = installs.get(installKey);
            return install?.has ? install.last : undefined;
        },
    };
}

export const shareRelay = createShareRelay();
