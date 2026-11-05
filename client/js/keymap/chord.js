
export const MODIFIER_ORDER = Object.freeze(['ctrl', 'alt', 'shift', 'cmd']);

const MODIFIER_ALIASES = Object.freeze({
    control: 'ctrl', ctrl: 'ctrl', alt: 'alt', option: 'alt', opt: 'alt',
    shift: 'shift', cmd: 'cmd', command: 'cmd', meta: 'cmd', super: 'cmd',
});

const KEY_ALIASES = Object.freeze({
    esc: 'escape', return: 'enter', plus: '+', up: 'arrowup', down: 'arrowdown', left: 'arrowleft', right: 'arrowright',
    spacebar: 'space', del: 'delete',
});

const CAP_WORDS = Object.freeze({
    escape: 'esc', arrowup: 'up', arrowdown: 'down', arrowleft: 'left', arrowright: 'right',
});

function splitChord(text) {
    const raw = String(text).trim();
    if (raw === '+') return { mods: [], key: '+' };
    const plusKey = raw.endsWith('++');
    const body = plusKey ? raw.slice(0, -2) : raw;
    const parts = body === '' ? [] : body.split('+');
    if (plusKey) return { mods: parts, key: '+' };
    const key = parts.pop() ?? '';
    return { mods: parts, key };
}

function isSymbolKey(key) {
    return key.length === 1 && !/[a-z0-9]/.test(key) && key !== ' ';
}

export function normalize(text) {
    const { mods, key } = splitChord(text);
    return compose(mods.map((word) => MODIFIER_ALIASES[word.toLowerCase()]).filter(Boolean), key);
}

function compose(mods, key) {
    const lower = String(key).toLowerCase();
    const name = KEY_ALIASES[lower] ?? lower;
    if (name === '') return '';
    const found = new Set(mods);
    if (isSymbolKey(name)) found.delete('shift');
    const head = MODIFIER_ORDER.filter((m) => found.has(m));
    return name === '+' ? [...head, '+'].join('+').replace(/^\+$/, '+') : [...head, name].join('+');
}

export function parse(chord) {
    return splitChord(normalize(chord));
}

export function caps(chord) {
    const { mods, key } = parse(chord);
    return [...mods, CAP_WORDS[key] ?? key];
}

export function formatChord(chord) {
    return caps(chord).join(' ');
}

export function chordFromEvent(event) {
    const key = String(event.key ?? '');
    if (key === '' || key === 'Dead' || key === 'Unidentified' || MODIFIER_ALIASES[key.toLowerCase()]) return null;
    let name = /^contextmenu$/i.test(key) ? 'menu' : key === ' ' ? 'space' : key;
    const code = String(event.code ?? '');
    if (event.altKey && /^(Key[A-Z]|Digit[0-9])$/.test(code)) name = code.slice(-1);
    const mods = [event.ctrlKey && 'ctrl', event.altKey && 'alt', event.shiftKey && 'shift', event.metaKey && 'cmd'].filter(Boolean);
    return compose(mods, name);
}

export function matchesChord(chord, event) {
    const pressed = chordFromEvent(event);
    return pressed !== null && pressed === normalize(chord);
}
