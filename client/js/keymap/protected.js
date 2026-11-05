/* the same words */
import { parse, normalize } from './chord.js';
import { scopesOverlap } from './scopes.js';

export const RESERVED = Object.freeze({
    mac: Object.freeze(['cmd+c', 'cmd+v', 'cmd+x', 'cmd+a', 'cmd+z', 'shift+cmd+z', 'cmd+q', 'cmd+w', 'cmd+h', 'cmd+m', 'cmd+space', 'cmd+tab',
        'cmd+t', 'cmd+l', 'cmd+d', 'shift+cmd+t']),
    other: Object.freeze(['ctrl+c', 'ctrl+v', 'ctrl+x', 'ctrl+a', 'ctrl+z', 'ctrl+w', 'ctrl+t', 'ctrl+n', 'ctrl+tab', 'ctrl+shift+t',
        'ctrl+shift+n', 'ctrl+shift+w', 'alt+f4', 'alt+tab', 'ctrl+shift+tab']),
});

export const REFUSAL_CODES = Object.freeze([
    'malformed', 'reserved', 'escape', 'tab', 'terminal_owned', 'needs_modifier', 'needs_cmd', 'no_ctrl_alt', 'needs_ctrl_shift',
]);

const TERMINAL_OWNER_SCOPES = Object.freeze(['terminal-pane', 'terminal-screen', 'field', 'overlay:terminal-search']);

export function terminalOwned(actions, family) {
    const found = new Set();
    for (const a of actions) if (TERMINAL_OWNER_SCOPES.includes(a.scope)) for (const c of a.keys[family] ?? []) found.add(c);
    return [...found].sort();
}

export const inTextInput = (scope) => scope === 'field' || scope.startsWith('overlay:');

export function reachesTerminal(scope) {
    return scopesOverlap(scope, 'terminal-pane', true);
}

export function refusal(family, chord, scope, actions) {
    if (normalize(chord) !== chord) return 'malformed';
    const { mods, key } = parse(chord);
    if (RESERVED[family].includes(chord)) return 'reserved';
    if (key === 'escape') return 'escape';
    if (key === 'tab') return 'tab';
    if (terminalOwned(actions, family).includes(chord)) return 'terminal_owned';
    if (inTextInput(scope) && !mods.some((m) => m === 'ctrl' || m === 'alt' || m === 'cmd')) return 'needs_modifier';
    if (!reachesTerminal(scope)) return null;
    if (family === 'mac') return mods.includes('cmd') ? null : 'needs_cmd';
    if (mods.includes('ctrl') && mods.includes('alt')) return 'no_ctrl_alt';
    return mods.includes('ctrl') && mods.includes('shift') ? null : 'needs_ctrl_shift';
}
