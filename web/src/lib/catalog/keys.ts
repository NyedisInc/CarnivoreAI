import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';

export type KeyAction =
    | 'search'
    | 'next'
    | 'prev'
    | 'open'
    | 'install'
    | 'try'
    | 'update'
    | 'help';

const BY_KEY: Readonly<Record<string, KeyAction>> = {
    '/': 'search',
    j: 'next',
    k: 'prev',
    Enter: 'open',
    i: 'install',
    t: 'try',
    u: 'update',
    '?': 'help',
};

export function keyAction(
    event: { key: string; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean },
    typing: boolean,
    pressable = false,
): KeyAction | null {
    if (typing || event.ctrlKey || event.metaKey || event.altKey) return null;
    if (pressable && event.key === 'Enter') return null;
    return BY_KEY[event.key] ?? null;
}

export function isPressable(target: EventTarget | null): boolean {
    const el = target as HTMLElement | null;
    if (!el || typeof el.closest !== 'function') return false;
    return el.closest('button, a[href], [role="button"], summary') !== null;
}

export function isTyping(target: EventTarget | null): boolean {
    const el = target as HTMLElement | null;
    if (!el || typeof el.tagName !== 'string') return false;
    const tag = el.tagName.toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable === true;
}

export const CATALOG_KEY_ROWS: ReadonlyArray<readonly [string, string]> = [
    ['/', BROWSE_KEYS.keysSearch],
    ['j  k', BROWSE_KEYS.keysMove],
    ['enter', BROWSE_KEYS.keysOpen],
    ['i', BROWSE_KEYS.keysInstall],
    ['t', BROWSE_KEYS.keysTry],
    ['u', BROWSE_KEYS.keysUpdate],
    ['?', BROWSE_KEYS.keysHelp],
];
