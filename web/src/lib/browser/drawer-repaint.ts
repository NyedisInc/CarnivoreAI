
export function repaintDrawer(): void {
    const bar = (globalThis as { SessionSidebar?: { _lastSig?: unknown; _fetchAndRender?: () => Promise<void> } })
        .SessionSidebar;
    if (typeof bar?._fetchAndRender !== 'function') return;
    bar._lastSig = null;
    void bar._fetchAndRender();
}

export function reselectDrawer(): void {
    queueMicrotask(() => {
        (globalThis as { SessionSidebar?: { refreshSelection?: () => void } }).SessionSidebar?.refreshSelection?.();
    });
}
