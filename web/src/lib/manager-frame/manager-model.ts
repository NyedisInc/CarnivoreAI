import type { ManagerFilter, ManagerItem } from './types';

export const MANAGER_KEYS = {
    searchLabel: 'manager.search.label',
    searchPlaceholder: 'manager.search.placeholder',
    filtersLabel: 'manager.filters.label',
    count: 'manager.count',
    countFiltered: 'manager.count.filtered',
    loading: 'manager.loading',
    errorTitle: 'manager.error.title',
    errorRetry: 'manager.error.retry',
    empty: 'manager.empty',
    emptyFiltered: 'manager.empty.filtered',
    clear: 'manager.clear',
    toggleOn: 'manager.toggle.on',
    toggleOff: 'manager.toggle.off',
    toggleWorking: 'manager.toggle.working',
    toggleLabel: 'manager.toggle.label',
    viewLabel: 'manager.view.label',
    viewGrid: 'manager.view.grid',
    viewList: 'manager.view.list',
    viewFlipToList: 'manager.view.flip_to_list',
    viewFlipToGrid: 'manager.view.flip_to_grid',
    close: 'manager.close',
    detailBack: 'manager.detail.back',
    detailLabel: 'manager.detail.label',
    install: 'manager.install',
    limitsLabel: 'manager.limits.label',
    actionsLabel: 'manager.actions.label',
    exportAction: 'manager.export',
    exported: 'manager.export.done',
    removeAction: 'manager.remove',
    removeQuestion: 'manager.remove.question',
    removeConfirm: 'manager.remove.confirm',
    removeCancel: 'manager.remove.cancel',
    removed: 'manager.remove.done',
    working: 'manager.working',
    facetState: 'manager.facet.state',
    facetAll: 'manager.facet.all',
    sortLabel: 'manager.sort.label',
} as const;

export function matchesQuery(item: ManagerItem, query: string): boolean {
    const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (terms.length === 0) return true;
    const haystack = [item.name, item.brief ?? '', item.meta ?? '', ...(item.marks ?? []), ...(item.tags ?? []), item.byline ?? '']
        .join('\n')
        .toLowerCase();
    return terms.every((term) => haystack.includes(term));
}

export function visibleItems(
    items: readonly ManagerItem[],
    query: string,
    filters: readonly ManagerFilter[],
): ManagerItem[] {
    const pressed = filters.filter((filter) => filter.on);
    return items.filter(
        (item) => matchesQuery(item, query) && pressed.every((filter) => filter.test(item)),
    );
}

export function isNarrowed(query: string, filters: readonly ManagerFilter[]): boolean {
    return query.trim() !== '' || filters.some((filter) => filter.on);
}

export function isSwitchable(item: ManagerItem, wired: boolean): boolean {
    return wired && typeof item.enabled === 'boolean';
}

export interface ManagerItemGroup {
    readonly id: string;
    readonly items: readonly ManagerItem[];
}

export function groupItems(
    shown: readonly ManagerItem[],
    order: readonly string[],
    groupOf: (item: ManagerItem) => string,
    narrowed: boolean,
): ManagerItemGroup[] {
    const ids = [...order];
    for (const item of shown) {
        const id = groupOf(item);
        if (!ids.includes(id)) ids.push(id);
    }
    return ids
        .map((id) => ({ id, items: shown.filter((item) => groupOf(item) === id) }))
        .filter((group) => !narrowed || group.items.length > 0);
}
