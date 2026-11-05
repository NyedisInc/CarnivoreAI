/* the widgets page */
import { readTab, writeTab } from '../../../opscenter/ui/tab-memory';

export type WidgetsTab = 'widgets' | 'settings';
export const WIDGETS_TABS: readonly WidgetsTab[] = ['widgets', 'settings'];
const MEMORY_KEY = 'widgets-page';

export function tabFromLocation(hash: string, search: string): WidgetsTab | null {
    if (hash === '#widgets/settings') return 'settings';
    if (hash === '#widgets' && new URLSearchParams(search).get('tab') === 'settings') return 'settings';
    return null;
}

export function initialTab(hash: string, search: string): WidgetsTab {
    return tabFromLocation(hash, search) ?? readTab(MEMORY_KEY, WIDGETS_TABS, 'widgets');
}

export function hashForTab(tab: WidgetsTab): string {
    return tab === 'settings' ? '#widgets/settings' : '#widgets';
}

export function commitTab(tab: WidgetsTab, target: Window | null = typeof window !== 'undefined' ? window : null): void {
    writeTab(MEMORY_KEY, tab);
    if (!target) return;
    const params = new URLSearchParams(target.location.search);
    params.delete('tab');
    const query = params.toString();
    target.history.replaceState(target.history.state, '', `${target.location.pathname}${query ? `?${query}` : ''}${hashForTab(tab)}`);
}

export function commitOnOpen(tab: WidgetsTab, target: Window | null = typeof window !== 'undefined' ? window : null): void {
    if (target && new URLSearchParams(target.location.search).has('tab')) commitTab(tab, target);
}
