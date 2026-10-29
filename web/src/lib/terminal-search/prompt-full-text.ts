/* first paragraph */

function fold(text: string): string {
    return text.split(/\s+/).filter(Boolean).join(' ');
}

/* first paragraph */
function firstParagraph(text: string): string {
    return fold(text.split(/\n[ \t]*\n/)[0] ?? '');
}

/* first paragraph */
function sameStart(scanned: string, transcriptPrompt: string): boolean {
    const a = fold(scanned);
    const b = firstParagraph(transcriptPrompt);
    if (!a || !b) return false;
    return a === b || a.startsWith(b) || b.startsWith(a);
}

export function matchFullTexts(
    scanned: ReadonlyArray<{ ordinal: number; text: string }>,
    transcript: readonly string[],
): Map<number, string> {
    const out = new Map<number, string>();
    let cursor = transcript.length - 1;
    for (let i = scanned.length - 1; i >= 0; i--) {
        const s = scanned[i];
        if (!s) continue;
        for (let k = cursor; k >= 0; k--) {
            const candidate = transcript[k];
            if (candidate !== undefined && sameStart(s.text, candidate)) {
                out.set(s.ordinal, candidate);
                cursor = k - 1;
                break;
            }
        }
    }
    return out;
}
