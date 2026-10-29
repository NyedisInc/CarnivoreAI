
export const HIGHLIGHT_CLASS = 'st-highlight-flash';
export const HIGHLIGHT_MS = 1600;
export const HIGHLIGHT_WAIT_MS = 4000;

function find(root: ParentNode, id: string): HTMLElement | null {
    for (const el of root.querySelectorAll<HTMLElement>('[data-highlight]')) if (el.dataset.highlight === id) return el;
    return null;
}

function flash(el: HTMLElement): void {
    el.scrollIntoView?.({ block: 'center' });
    el.classList.add(HIGHLIGHT_CLASS);
    setTimeout(() => el.classList.remove(HIGHLIGHT_CLASS), HIGHLIGHT_MS);
}

export function highlightControl(root: ParentNode & Node, id: string, waitMs: number = HIGHLIGHT_WAIT_MS): Promise<boolean> {
    const now = find(root, id);
    if (now) {
        flash(now);
        return Promise.resolve(true);
    }
    return new Promise((resolve) => {
        const observer = new MutationObserver(() => {
            const el = find(root, id);
            if (!el) return;
            stop();
            flash(el);
            resolve(true);
        });
        const timer = setTimeout(() => {
            stop();
            resolve(false);
        }, waitMs);
        function stop(): void {
            observer.disconnect();
            clearTimeout(timer);
        }
        observer.observe(root, { childList: true, subtree: true });
    });
}
