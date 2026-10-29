import type { CardView } from './card';

export const MAX_IMAGE_BYTES = 512 * 1024;
export const MIN_IMAGE_WIDTH = 1200;
export const MIN_IMAGE_HEIGHT = 500;
export const MAX_IMAGE_SIDE = 8192;
export const MAX_IMAGE_PIXELS = 16_000_000;
export const RATIO_MIN = 1.5;
export const RATIO_MAX = 3.0;

const IMAGE_KINDS: readonly string[] = ['skill', 'theme', 'plugin'];

export type ImageType = 'png' | 'jpeg' | 'webp';

export type HeroCheck =
    | { ok: true; type: ImageType; w: number; h: number }
    | { ok: false; key: string; params?: Record<string, unknown> };

export function readImageSize(bytes: Uint8Array): { type: ImageType; w: number; h: number } | null {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const at = (i: number): number => bytes[i] ?? -1;
    const ascii = (i: number, text: string): boolean => [...text].every((c, k) => at(i + k) === c.charCodeAt(0));
    if (bytes.length >= 24 && [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a].every((b, k) => at(k) === b)) {
        if (!ascii(12, 'IHDR')) return null;
        return { type: 'png', w: view.getUint32(16), h: view.getUint32(20) };
    }
    if (at(0) === 0xff && at(1) === 0xd8 && at(2) === 0xff) {
        let i = 2;
        while (i + 9 < bytes.length) {
            if (at(i) !== 0xff) return null;
            const marker = at(i + 1);
            if (marker === 0xff) {
                i += 1;
                continue;
            }
            if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
                i += 2;
                continue;
            }
            if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
                return { type: 'jpeg', h: view.getUint16(i + 5), w: view.getUint16(i + 7) };
            }
            i += 2 + view.getUint16(i + 2);
        }
        return null;
    }
    if (bytes.length >= 30 && ascii(0, 'RIFF') && ascii(8, 'WEBP')) {
        if (ascii(12, 'VP8 ') && at(23) === 0x9d && at(24) === 0x01 && at(25) === 0x2a) {
            return { type: 'webp', w: view.getUint16(26, true) & 0x3fff, h: view.getUint16(28, true) & 0x3fff };
        }
        if (ascii(12, 'VP8L') && at(20) === 0x2f) {
            const bits = view.getUint32(21, true);
            return { type: 'webp', w: (bits & 0x3fff) + 1, h: ((bits >>> 14) & 0x3fff) + 1 };
        }
        if (ascii(12, 'VP8X')) {
            const w = at(24) | (at(25) << 8) | (at(26) << 16);
            const h = at(27) | (at(28) << 8) | (at(29) << 16);
            return { type: 'webp', w: w + 1, h: h + 1 };
        }
    }
    return null;
}

export function checkHeroImage(bytes: Uint8Array, size: number): HeroCheck {
    if (size > MAX_IMAGE_BYTES) return { ok: false, key: 'skill.publish.hero.too_big' };
    const found = readImageSize(bytes);
    if (!found) return { ok: false, key: 'skill.publish.refused.bad_image' };
    const { type, w, h } = found;
    if (w < MIN_IMAGE_WIDTH || h < MIN_IMAGE_HEIGHT) {
        return { ok: false, key: 'skill.publish.card_image.too_small', params: { w: String(w), h: String(h) } };
    }
    if (w > MAX_IMAGE_SIDE || h > MAX_IMAGE_SIDE || w * h > MAX_IMAGE_PIXELS) {
        return { ok: false, key: 'skill.publish.card_image.too_many_px', params: { w: String(w), h: String(h) } };
    }
    const ratio = w / h;
    if (ratio < RATIO_MIN || ratio > RATIO_MAX) {
        return { ok: false, key: 'skill.publish.card_image.bad_shape', params: { ratio: ratio.toFixed(1) } };
    }
    return { ok: true, type, w, h };
}

export function ownsItem(
    handle: string | null | undefined,
    card: Pick<CardView, 'kind' | 'id' | 'publisher'>,
): boolean {
    if (!handle || !card.id || !card.publisher || !card.kind) return false;
    if (!IMAGE_KINDS.includes(card.kind)) return false;
    const me = handle.toLowerCase();
    return me === card.publisher.toLowerCase() && me === (card.id.split('/')[0] ?? '').toLowerCase();
}

export function readBytes(file: Blob): Promise<Uint8Array> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
        reader.onerror = () => reject(reader.error ?? new Error());
        reader.readAsArrayBuffer(file);
    });
}
