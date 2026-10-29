
export const DEVICE_STORAGE_KEY = 'carnivore.notify.device';

const SHAPE = /^b_[0-9a-f]{16,32}$/;
let pageKey: string | null = null;

function mint(): string {
    const bytes = new Uint8Array(8);
    globalThis.crypto.getRandomValues(bytes);
    return 'b_' + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function deviceKey(): string | null {
    try {
        const stored = globalThis.localStorage?.getItem(DEVICE_STORAGE_KEY);
        if (stored && SHAPE.test(stored)) return stored;
        const fresh = mint();
        globalThis.localStorage?.setItem(DEVICE_STORAGE_KEY, fresh);
        return fresh;
    } catch {
        try {
            pageKey = pageKey ?? mint();
            return pageKey;
        } catch {
            return null;
        }
    }
}

export function deviceLabel(): string {
    const coarse = globalThis.matchMedia?.('(pointer: coarse)').matches === true;
    return coarse ? 'phone' : 'computer';
}
