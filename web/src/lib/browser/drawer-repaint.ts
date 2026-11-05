
export function repaintDrawer(): void {
    const bar = (globalThis as { SessionSidebar?: { _fetchAndRender?: () => Promise<void> } })
        .SessionSidebar;
    if (typeof bar?._fetchAndRender !== 'function') return;
    void bar._fetchAndRender();
}

export function reselectDrawer(): void {
    queueMicrotask(() => {
        (globalThis as { SessionSidebar?: { refreshSelection?: () => void } }).SessionSidebar?.refreshSelection?.();
    });
}
