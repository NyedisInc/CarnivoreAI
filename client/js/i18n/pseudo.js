/* padding */

export const PSEUDO_OPEN = '⟦';

export const PSEUDO_CLOSE = '⟧';

/* padding */
export const PSEUDO_PAD = '~';

export const PSEUDO_EXPANSION = 0.4;

export const PSEUDO_LOCALE = 'pseudo';

/* padding */
export function pseudoText(text) {
    if (typeof text !== 'string') return text;
    const pad = Math.max(1, Math.ceil(text.length * PSEUDO_EXPANSION));
    return PSEUDO_OPEN + text + ' ' + PSEUDO_PAD.repeat(pad) + PSEUDO_CLOSE;
}

export function isPseudo(text) {
    if (typeof text !== 'string' || text.length < 2) return false;
    if (!text.startsWith(PSEUDO_OPEN) || !text.endsWith(PSEUDO_CLOSE)) return false;
    let depth = 0;
    for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        if (ch === PSEUDO_OPEN) depth += 1;
        else if (ch === PSEUDO_CLOSE) {
            depth -= 1;
            if (depth < 0) return false;
            if (depth === 0 && i !== text.length - 1) return false;
        }
    }
    return depth === 0;
}

export function pseudoCount(text) {
    if (typeof text !== 'string') return 0;
    let n = 0;
    for (let i = 0; i < text.length; i++) {
        if (text[i] === PSEUDO_OPEN) n += 1;
    }
    return n;
}

export function pseudoCatalog(source) {
    const out = {};
    for (const key of Object.keys(source || {})) {
        const value = source[key];
        if (typeof value === 'string') {
            out[key] = pseudoText(value);
            continue;
        }
        if (value && typeof value === 'object') {
            const forms = {};
            for (const category of Object.keys(value)) {
                forms[category] = pseudoText(value[category]);
            }
            out[key] = forms;
            continue;
        }
        out[key] = value;
    }
    return out;
}
