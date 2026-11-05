
export interface AppKeyEvent {
    key: string;
    code?: string;
    metaKey?: boolean;
    ctrlKey?: boolean;
    altKey?: boolean;
    shiftKey?: boolean;
    isComposing?: boolean;
    repeat?: boolean;
    target?: EventTarget | null;
}

export interface AppChord {
    id: string;
    key: string;
    meta?: boolean;
    ctrl?: boolean;
    alt?: boolean;
    shift?: boolean;
    anyShift?: boolean;
    accelerator: string;
    keys: string;
    labelKey: string;
    inFields?: boolean;
    run(event: AppKeyEvent): boolean | void;
}

export function isTextField(target: EventTarget | null | undefined): boolean {
    const el = target as (Element & { isContentEditable?: boolean }) | null | undefined;
    if (!el || typeof el.closest !== 'function') return false;
    if (el.closest('.xterm-helper-textarea, .xterm')) return false;
    if (el.isContentEditable) return true;
    const tag = String(el.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select';
}

export function matches(chord: AppChord, event: AppKeyEvent): boolean {
    const physical = event.altKey && /^(Key[A-Z]|Digit[0-9])$/.test(event.code ?? '') ? String(event.code).slice(-1).toLowerCase() : String(event.key).toLowerCase();
    if (physical !== chord.key) return false;
    return !!event.metaKey === !!chord.meta && !!event.ctrlKey === !!chord.ctrl
        && !!event.altKey === !!chord.alt && (chord.anyShift === true || !!event.shiftKey === !!chord.shift);
}

export function pick(chords: readonly AppChord[], event: AppKeyEvent): AppChord | null {
    if (event.isComposing || event.key === 'Process') return null;
    const chord = chords.find((c) => matches(c, event));
    if (!chord) return null;
    if (!chord.inFields && isTextField(event.target)) return null;
    return chord;
}

export function installAppKeys(chords: readonly AppChord[] | (() => readonly AppChord[]), doc: Document): () => void {
    const onKeyDown = (event: Event): void => {
        const e = event as KeyboardEvent;
        const chord = pick(typeof chords === 'function' ? chords() : chords, e);
        if (!chord || chord.run(e) === false) return;
        e.preventDefault();
        e.stopPropagation();
    };
    doc.addEventListener('keydown', onKeyDown, true);
    return () => doc.removeEventListener('keydown', onKeyDown, true);
}
