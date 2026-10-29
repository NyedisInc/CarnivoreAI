export interface SnippetPart {
    readonly text: string;
    readonly match: boolean;
}

const MARK_OPEN = '\u0002';
const MARK_CLOSE = '\u0003';

export function snippetParts(snippet: string): SnippetPart[] {
    const parts: SnippetPart[] = [];
    let rest = snippet;
    while (rest.length > 0) {
        const open = rest.indexOf(MARK_OPEN);
        if (open < 0) {
            parts.push({ text: rest, match: false });
            break;
        }
        if (open > 0) parts.push({ text: rest.slice(0, open), match: false });
        const close = rest.indexOf(MARK_CLOSE, open + 1);
        const end = close < 0 ? rest.length : close;
        const word = rest.slice(open + 1, end);
        if (word) parts.push({ text: word, match: true });
        rest = close < 0 ? '' : rest.slice(close + 1);
    }
    return parts.map((p) => ({ text: p.text.split(MARK_OPEN).join('').split(MARK_CLOSE).join(''), match: p.match }));
}
