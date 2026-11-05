import { caps, formatChord, normalize } from './chord.js';
import { scopesOverlap } from './scopes.js';

export function chordsOf(action, family, overrides) {
    const own = action.rebindable ? overrides?.[family]?.[action.id] : undefined;
    return Array.isArray(own) ? own.map(normalize).filter((c) => c !== '') : [...(action.keys[family] ?? [])];
}

const countsForClashes = (action) => action.category !== 'standard';

function sharesOnPurpose(a, b) {
    if (a.mayShare && b.mayShare) return true;
    const overlayOver = (top, under) => top.mayShare && top.scope.startsWith('overlay:') && (under.scope === 'global' || under.scope === 'field');
    return overlayOver(a, b) || overlayOver(b, a);
}

export function conflicts(actions, family, overrides) {
    const byChord = new Map();
    for (const action of actions.filter(countsForClashes)) {
        for (const chord of chordsOf(action, family, overrides)) {
            if (!byChord.has(chord)) byChord.set(chord, []);
            byChord.get(chord).push(action);
        }
    }
    const found = [];
    for (const [chord, holders] of byChord) {
        const hasCmd = chord.split('+').includes('cmd');
        for (let i = 0; i < holders.length; i += 1) {
            for (let j = i + 1; j < holders.length; j += 1) {
                const [a, b] = [holders[i], holders[j]];
                if (sharesOnPurpose(a, b)) continue;
                if (scopesOverlap(a.scope, b.scope, hasCmd)) found.push({ chord, a: a.id, b: b.id });
            }
        }
    }
    return found;
}

export function searchText(action, family, t, overrides) {
    const labels = [action.labelKey, ...action.altLabelKeys].map((key) => t(key));
    const keys = chordsOf(action, family, overrides).map(formatChord);
    return [...labels, action.id.replace(/[._]/g, ' '), action.category, action.scope, ...keys, ...action.mouse].join(' ').toLowerCase();
}

export function findByName(actions, query, family, t, overrides) {
    const words = String(query ?? '').toLowerCase().split(/\s+/).filter(Boolean);
    if (words.length === 0) return [...actions];
    return actions.filter((action) => {
        const text = searchText(action, family, t, overrides);
        return words.every((word) => text.includes(word));
    });
}

export function findByChord(actions, chord, family, overrides) {
    const wanted = normalize(chord);
    if (wanted === '') return [];
    const holders = actions.filter((action) => chordsOf(action, family, overrides).includes(wanted));
    const clashing = new Set(conflicts(holders, family, overrides).flatMap((c) => [c.a, c.b]));
    return [...holders.filter((a) => clashing.has(a.id)), ...holders.filter((a) => !clashing.has(a.id))];
}

export function groupByCategory(actions, order) {
    return order
        .map((category) => ({ category, actions: actions.filter((a) => a.category === category) }))
        .filter((group) => group.actions.length > 0);
}

export function capRows(action, family, overrides) {
    return chordsOf(action, family, overrides).map(caps);
}
