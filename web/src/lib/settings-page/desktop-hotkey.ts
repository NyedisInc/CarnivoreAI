
export interface KeyPress {
    code: string;
    ctrlKey: boolean;
    altKey: boolean;
    shiftKey: boolean;
    metaKey: boolean;
}

const NAMED: Readonly<Record<string, string>> = {
    Space: 'Space', Enter: 'Enter', Tab: 'Tab', Escape: 'Escape', Backspace: 'Backspace', Delete: 'Delete', Insert: 'Insert',
    Home: 'Home', End: 'End', PageUp: 'PageUp', PageDown: 'PageDown', ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right',
};

export function acceleratorOf(press: KeyPress): string | null {
    const letter = /^Key([A-Z])$/.exec(press.code);
    const digit = /^Digit([0-9])$/.exec(press.code);
    const fn = /^F([1-9]|1[0-9]|2[0-4])$/.exec(press.code);
    const key = letter?.[1] ?? digit?.[1] ?? (fn ? press.code : null) ?? NAMED[press.code] ?? null;
    if (!key) return null;
    const mods = [press.ctrlKey && 'Ctrl', press.altKey && 'Option', press.shiftKey && 'Shift', press.metaKey && 'Cmd'].filter(Boolean) as string[];
    if (mods.length === 0 || (mods.length === 1 && !fn)) return null;
    return [...mods, key].join('+');
}
