
export interface WordSpan {
    word: string;
    start: number;
    end: number;
}

export interface Segment {
    text: string;
    hit: boolean;
}

const WORD = /[\p{L}\p{N}]+/gu;

export type SearchMode = 'plain' | 'fuzzy';

const SCORE = { exact: 1, prefix: 0.9, substring: 0.7, fuzzy: 0.5 } as const;

export function wordSpans(text: string): WordSpan[] {
    const spans: WordSpan[] = [];
    for (const m of text.matchAll(WORD)) {
        const start = m.index ?? 0;
        spans.push({ word: m[0].toLowerCase(), start, end: start + m[0].length });
    }
    return spans;
}

export function parseQuery(query: string): string[] {
    return [...new Set(wordSpans(query).map((s) => s.word))];
}

export function allowedEdits(length: number): number {
    if (length < 4) return 0;
    return length < 6 ? 1 : 2;
}

export function boundedDistance(a: string, b: string, limit: number): number {
    if (Math.abs(a.length - b.length) > limit) return limit + 1;
    let prev2: number[] = [];
    let prev: number[] = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
        const row: number[] = [i];
        let best = i;
        for (let j = 1; j <= b.length; j++) {
            const cost = a[i - 1] === b[j - 1] ? 0 : 1;
            let d = Math.min(prev[j]! + 1, row[j - 1]! + 1, prev[j - 1]! + cost);
            if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
                d = Math.min(d, prev2[j - 2]! + 1);
            }
            row.push(d);
            if (d < best) best = d;
        }
        if (best > limit) return limit + 1;
        prev2 = prev;
        prev = row;
    }
    return Math.min(prev[b.length]!, limit + 1);
}

interface WordHit {
    score: number;
    from: number;
    to: number;
}

function matchWord(token: string, word: string, mode: SearchMode): WordHit | null {
    if (word === token) return { score: SCORE.exact, from: 0, to: word.length };
    if (word.startsWith(token)) return { score: SCORE.prefix, from: 0, to: token.length };
    if (mode === 'fuzzy' && token.length < 3) return null;
    const at = word.indexOf(token);
    if (at >= 0) return { score: SCORE.substring, from: at, to: at + token.length };
    if (mode === 'plain') return null;
    const edits = allowedEdits(token.length);
    if (edits === 0) return null;
    for (let len = token.length - edits; len <= token.length + edits; len++) {
        if (len < 1 || len > word.length) continue;
        const d = boundedDistance(token, word.slice(0, len), edits);
        if (d <= edits) {
            return { score: SCORE.fuzzy - 0.05 * d, from: 0, to: word.length };
        }
    }
    return null;
}

export function scoreTexts(tokens: readonly string[], texts: readonly string[], mode: SearchMode = 'fuzzy'): number {
    if (tokens.length === 0) return 0;
    const words = texts.flatMap((text) => wordSpans(text).map((s) => s.word));
    let total = 0;
    for (const token of tokens) {
        let best = 0;
        for (const word of words) {
            const hit = matchWord(token, word, mode);
            if (hit && hit.score > best) best = hit.score;
            if (best === SCORE.exact) break;
        }
        if (best === 0) return 0;
        total += best;
    }
    return total;
}

export function highlightSegments(text: string, tokens: readonly string[], mode: SearchMode = 'fuzzy'): Segment[] {
    const marks: Array<[number, number]> = [];
    for (const span of wordSpans(text)) {
        let best: WordHit | null = null;
        for (const token of tokens) {
            const hit = matchWord(token, span.word, mode);
            if (hit && (!best || hit.score > best.score)) best = hit;
        }
        if (best) marks.push([span.start + best.from, span.start + best.to]);
    }
    if (marks.length === 0) return [{ text, hit: false }];
    const out: Segment[] = [];
    let at = 0;
    for (const [from, to] of marks) {
        if (from > at) out.push({ text: text.slice(at, from), hit: false });
        out.push({ text: text.slice(from, to), hit: true });
        at = to;
    }
    if (at < text.length) out.push({ text: text.slice(at), hit: false });
    return out;
}
