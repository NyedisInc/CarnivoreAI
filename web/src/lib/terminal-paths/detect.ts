
export interface PathCandidate {
    text: string;
    start: number;
    end: number;
}

export const MAX_PER_ROW = 32;

const URL_SPAN = /[a-z][a-z0-9+.-]*:\/\/\S+/gi;

const TOKEN = /[\w.~/+@%-]+(?::\d+(?::\d+)?)?/g;

const BARE_NAME = /^[\w@+-][\w.@+-]*\.[A-Za-z][A-Za-z0-9]{0,9}(?::\d+(?::\d+)?)?$/;

const TRAILING = /\.+$/;

export function looksLikePath(token: string): boolean {
    const name = token.replace(/:\d+(?::\d+)?$/, '');
    if (name.length < 2 || !/[A-Za-z]/.test(name)) return false;
    if (name.startsWith('/') || name.startsWith('~/')) return name.length > 2;
    if (name.includes('/')) return !name.startsWith('//') && /[\w]/.test(name.replace(/[/.~]/g, ''));
    return BARE_NAME.test(token);
}

export function findPathCandidates(line: string): PathCandidate[] {
    const masked = line.replace(URL_SPAN, (url) => ' '.repeat(url.length));
    const out: PathCandidate[] = [];
    for (const match of masked.matchAll(TOKEN)) {
        const text = match[0].replace(TRAILING, '');
        if (!looksLikePath(text)) continue;
        const start = match.index ?? 0;
        out.push({ text, start, end: start + text.length });
        if (out.length >= MAX_PER_ROW) break;
    }
    return out;
}
