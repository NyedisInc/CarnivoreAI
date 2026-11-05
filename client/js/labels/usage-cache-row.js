import { USAGE_PANEL_KEYS, compactTokens, pairText, toNumber } from './usage-panel.js';

const CACHE_LABEL_KEY = 'usage.tokens.cache';

const AFTER_KEY = 'tokens';

export function withCacheRow(rows, usage, t) {
    const read = toNumber(usage.cache_read_input_tokens);
    const write = toNumber(usage.cache_creation_input_tokens);
    if (read === null && write === null) return rows;
    const row = {
        key: 'cache',
        label: t(CACHE_LABEL_KEY),
        text: pairText(compactTokens(read), compactTokens(write), t, USAGE_PANEL_KEYS.countSeparator),
    };
    const at = rows.findIndex((r) => r.key === AFTER_KEY);
    return at < 0 ? [...rows, row] : [...rows.slice(0, at + 1), row, ...rows.slice(at + 1)];
}
