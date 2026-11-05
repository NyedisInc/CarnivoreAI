import { normalize } from './chord.js';

function chords(list) {
    return Object.freeze((list ?? []).map(normalize).filter((c) => c !== ''));
}

export function def(id, category, scope, keys, extra) {
    const perFamily = Array.isArray(keys) ? { mac: keys, other: keys } : keys;
    return Object.freeze({
        id,
        labelKey: extra.labelKey ?? `keymap.action.${id}`,
        altLabelKeys: Object.freeze(extra.altLabelKeys ?? []),
        category,
        scope,
        keys: Object.freeze({ mac: chords(perFamily.mac), other: chords(perFamily.other) }),
        mouse: Object.freeze(extra.mouse ?? []),
        menus: Object.freeze(extra.menus ?? []),
        rebindable: extra.rebindable === true,
        fixedKey: extra.fixedKey ?? 'keymap.fixed.not_yet',
        mayShare: extra.mayShare === true,
        owner: extra.owner,
    });
}
