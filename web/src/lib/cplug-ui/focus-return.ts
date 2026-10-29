export function keepFocusOut(doc: Document, win: Window, frame: () => HTMLIFrameElement | null, allow: () => boolean = () => false): () => void {
    let held: HTMLElement | null = null;
    const onFocusIn = (event: Event): void => {
        const el = event.target;
        if (el instanceof HTMLElement && el !== frame()) held = el;
    };
    const onBlur = (): void => {
        const f = frame();
        if (f && doc.activeElement === f && !allow()) {
            if (held && held.isConnected) held.focus();
            else f.blur();
        }
    };
    doc.addEventListener('focusin', onFocusIn, true);
    win.addEventListener('blur', onBlur);
    return () => {
        doc.removeEventListener('focusin', onFocusIn, true);
        win.removeEventListener('blur', onBlur);
    };
}
