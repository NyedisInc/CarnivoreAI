
export const ANCHOR_GAP_PX = 2;

export const VIEWPORT_MARGIN_PX = 8;

export interface AnchoredPopupOptions {
    onClose: () => void;
    fitVertically?: boolean;
}

export interface AnchoredPopup {
    readonly element: HTMLElement | null;
    open(el: HTMLElement, anchor: Element, mount: () => void): void;
    close(restoreFocus?: boolean): void;
}

export function createAnchoredPopup(options: AnchoredPopupOptions): AnchoredPopup {
    const fitVertically = options.fitVertically ?? true;
    let current: HTMLElement | null = null;
    let returnFocusTo: HTMLElement | null = null;
    let wired = false;

    function close(restoreFocus = false): void {
        options.onClose();
        if (current && current.parentNode) current.parentNode.removeChild(current);
        current = null;
        const target = returnFocusTo;
        returnFocusTo = null;
        if (restoreFocus && target && target.isConnected) target.focus();
    }

    function wire(): void {
        if (wired) return;
        document.addEventListener('mousedown', (e) => {
            if (current && e.target instanceof Node && !current.contains(e.target)) close();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && current) close(true);
        });
        wired = true;
    }

    function place(el: HTMLElement, box: DOMRect): void {
        const left = Math.min(box.left, window.innerWidth - el.offsetWidth - VIEWPORT_MARGIN_PX);
        el.style.left = `${Math.max(VIEWPORT_MARGIN_PX, Math.round(left))}px`;
        if (!fitVertically) return;
        const bottomGap = window.innerHeight - (box.bottom + ANCHOR_GAP_PX + el.offsetHeight) - VIEWPORT_MARGIN_PX;
        if (bottomGap < 0) el.style.top = `${Math.max(VIEWPORT_MARGIN_PX, Math.round(box.bottom + ANCHOR_GAP_PX + bottomGap))}px`;
    }

    return {
        get element() { return current; },
        close,
        open(el, anchor, mount) {
            const box = anchor.getBoundingClientRect();
            el.style.top = `${Math.round(box.bottom + ANCHOR_GAP_PX)}px`;
            document.body.appendChild(el);
            current = el;
            returnFocusTo = anchor instanceof HTMLElement ? anchor : null;
            mount();
            place(el, box);
            wire();
        },
    };
}
