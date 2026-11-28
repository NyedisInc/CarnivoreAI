export function modelColorKey(text: unknown): string {
    if (typeof text !== 'string') return '';
    const m = text.toLowerCase().match(/\b(neon|carbon|argon|hydrogen)\b|(fable|mythos|opus|sonnet|haiku)/);
    return m ? (m[1] ?? m[2] ?? '') : '';
}
