
export interface MatchParts {
    before: string;
    match: string;
    after: string;
}

export function matchParts(text: string, q: string): MatchParts {
    const at = q ? text.toLowerCase().indexOf(q) : -1;
    if (at < 0) return { before: text, match: '', after: '' };
    return { before: text.slice(0, at), match: text.slice(at, at + q.length), after: text.slice(at + q.length) };
}
