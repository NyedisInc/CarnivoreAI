import { SvelteMap } from 'svelte/reactivity';

export interface CardImagePreview {
    url: string;
    file: File;
    name: string;
    w: number;
    h: number;
    kb: number;
    sent: boolean;
}

const previews = new SvelteMap<string, CardImagePreview>();

export function previewFor(itemId: string | null | undefined): CardImagePreview | null {
    return itemId ? (previews.get(itemId) ?? null) : null;
}

export function setPreview(itemId: string, preview: CardImagePreview): void {
    const old = previews.get(itemId);
    if (old && old.url !== preview.url) URL.revokeObjectURL(old.url);
    previews.set(itemId, preview);
}

export function markSent(itemId: string): void {
    const held = previews.get(itemId);
    if (held) previews.set(itemId, { ...held, sent: true });
}

export function clearPreview(itemId: string): void {
    const old = previews.get(itemId);
    if (old) URL.revokeObjectURL(old.url);
    previews.delete(itemId);
}
