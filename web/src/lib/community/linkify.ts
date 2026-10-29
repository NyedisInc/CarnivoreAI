
export type Piece = { text: string; href?: undefined } | { text: string; href: string };

const CANDIDATE = /https?:\/\/[^\s<>"'`]+/gi;

const TRAILING = /[.,;:!?)\]}]+$/;

export function safeHref(raw: string): string | null {
    try {
        const url = new URL(raw);
        if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
        if (!url.hostname) return null;
        return url.href;
    } catch {
        return null;
    }
}

export function pieces(text: string): Piece[] {
    const out: Piece[] = [];
    let last = 0;
    for (const match of text.matchAll(CANDIDATE)) {
        const start = match.index ?? 0;
        const trimmed = match[0].replace(TRAILING, '');
        const href = safeHref(trimmed);
        if (!href) continue;
        if (start > last) out.push({ text: text.slice(last, start) });
        out.push({ text: trimmed, href });
        last = start + trimmed.length;
    }
    if (last < text.length) out.push({ text: text.slice(last) });
    return out;
}
