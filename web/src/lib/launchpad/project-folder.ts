
export const ILLEGAL_CHARS = ['/', '\\', '\u0000'] as const;

export const MAX_NAME_BYTES = 255;

export type NameRefusalCode =
    | 'required'
    | 'illegal_char'
    | 'illegal_null'
    | 'control_chars'
    | 'reserved'
    | 'leading_dot'
    | 'too_long';

export interface NameVerdict {
    ok: boolean;
    code: NameRefusalCode | null;
    params: Record<string, string | number>;
}

const ACCEPTED: NameVerdict = { ok: true, code: null, params: {} };

/* not a string */
export function validateName(name: unknown): NameVerdict {
    const raw = typeof name === 'string' ? name : '';
    const trimmed = raw.trim();

    if (!trimmed) return { ok: false, code: 'required', params: {} };

    for (const char of ILLEGAL_CHARS) {
        if (trimmed.indexOf(char) !== -1) {
            if (char === '\u0000') {
                return { ok: false, code: 'illegal_null', params: {} };
            }
            return { ok: false, code: 'illegal_char', params: { char } };
        }
    }
    for (let i = 0; i < trimmed.length; i += 1) {
        const code = trimmed.charCodeAt(i);
        if (code < 32 || code === 127) {
            return { ok: false, code: 'control_chars', params: {} };
        }
    }
    if (trimmed === '.' || trimmed === '..') {
        return { ok: false, code: 'reserved', params: {} };
    }
    if (trimmed.charAt(0) === '.') {
        return { ok: false, code: 'leading_dot', params: {} };
    }
    if (new TextEncoder().encode(trimmed).length > MAX_NAME_BYTES) {
        return { ok: false, code: 'too_long', params: { max: MAX_NAME_BYTES } };
    }
    return ACCEPTED;
}
