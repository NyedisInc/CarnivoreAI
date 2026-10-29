import { homeLayout, terminalLayout, warroomLayout, type LayoutStore } from '../../opscenter/engine/layout.svelte';

export const drawerSurface = $state<{ page: 'home' | 'terminal' | 'warroom' | null }>({ page: null });

export function surfacePage(doc: Document = document): 'home' | 'terminal' | 'warroom' | null {
    if (doc.querySelector('#warroom-screen .oc-surface')) return 'warroom';
    if (doc.getElementById('launchpad-screen')?.classList.contains('active')) return 'home';
    const terminal = doc.getElementById('terminal-screen');
    if (terminal?.classList.contains('active') && !terminal.classList.contains('terminal-screen--empty')
        && doc.querySelector('#terminal-grid .oc-surface')) return 'terminal';
    return null;
}

export function storeFor(page: 'home' | 'terminal' | 'warroom' | null): LayoutStore | null {
    if (page === 'home') return homeLayout;
    if (page === 'warroom') return warroomLayout;
    if (page === 'terminal') return terminalLayout;
    return null;
}

export function watchDrawerSurface(doc: Document = document): () => void {
    const update = () => {
        drawerSurface.page = surfacePage(doc);
    };
    update();
    if (typeof MutationObserver !== 'function') return () => {};
    const observer = new MutationObserver(update);
    for (const id of ['launchpad-screen', 'terminal-screen']) {
        const el = doc.getElementById(id);
        if (el) observer.observe(el, { attributes: true, attributeFilter: ['class'] });
    }
    const warroom = doc.getElementById('warroom-screen');
    if (warroom) observer.observe(warroom, { childList: true });
    const grid = doc.getElementById('terminal-grid');
    if (grid) observer.observe(grid, { childList: true });
    return () => observer.disconnect();
}
