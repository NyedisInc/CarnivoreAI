import type { Translate } from '../../sessions/types';
import { LOOK_PAGES, MENU_KINDS, nodeKey, type LookPage, type MenuKind, type MenuNode } from './route';

export interface InstalledEntry {
    readonly key: string;
    readonly title: string;
    readonly word: string;
    readonly catalogId?: string;
}

export interface FlaggedEntry extends InstalledEntry {
    readonly kind: MenuKind;
}

export interface StoreEntry {
    readonly kind: MenuKind;
    readonly id: string;
    readonly title: string;
    readonly installed: boolean;
}

export interface MenuSources {
    readonly storeTotal: number;
    readonly storeNewest: number;
    readonly storeUpdates: number;
    readonly storeByKind: Readonly<Record<MenuKind, number>>;
    readonly storeItems: readonly StoreEntry[];
    readonly installed: Readonly<Record<MenuKind, readonly InstalledEntry[]>>;
    readonly flagged: readonly FlaggedEntry[];
    readonly needs: readonly { readonly page: LookPage; readonly count: number }[];
}

export interface MenuRow {
    readonly key: string;
    readonly depth: 1 | 2;
    readonly label: string;
    readonly count?: number;
    readonly word?: string;
    readonly kind?: MenuKind;
    readonly icon?: string;
    readonly zero?: boolean;
    readonly hit?: boolean;
    readonly node: MenuNode;
    readonly children: readonly MenuRow[];
}

export type MenuGroupId = 'look' | 'store' | 'installed' | 'yours';

export interface MenuGroup {
    readonly id: MenuGroupId;
    readonly label: string;
    readonly rows: readonly MenuRow[];
}

export function kindPlural(kind: MenuKind, t: Translate): string {
    return t(`warez.kind.chip.${kind}`);
}

function row(node: MenuNode, label: string, depth: 1 | 2, extra: Partial<MenuRow> = {}): MenuRow {
    return { key: nodeKey(node), depth, label, node, children: [], ...extra };
}

const matches = (label: string, query: string): boolean => label.toLowerCase().includes(query);

function narrow(source: MenuRow, query: string): MenuRow | null {
    const self = matches(source.label, query);
    const kids = source.children.filter((child) => matches(child.label, query));
    if (!self && kids.length === 0) return null;
    return { ...source, hit: self, children: self ? source.children : kids };
}

export function buildMenu(sources: MenuSources, query: string, t: Translate, readonly = false): MenuGroup[] {
    const q = query.trim().toLowerCase();
    const store: MenuRow[] = [
        row({ scope: 'store', page: 'everything' }, t('warez.menu.everything'), 1, { count: sources.storeTotal }),
        row({ scope: 'store', page: 'newest' }, t('warez.menu.newest'), 1, { count: sources.storeNewest }),
        ...(readonly ? [] : [row({ scope: 'store', page: 'updates' }, t('warez.menu.updates'), 1, { count: sources.storeUpdates, zero: sources.storeUpdates === 0 })]),
        ...MENU_KINDS.map((kind) =>
            row({ scope: 'store', page: 'kind', kind }, kindPlural(kind, t), 1, {
                kind,
                count: sources.storeByKind[kind],
                children: q
                    ? sources.storeItems
                          .filter((entry) => entry.kind === kind && matches(entry.title, q))
                          .map((entry) => row({ scope: 'store', page: 'item', id: entry.id }, entry.title, 2, { word: entry.installed ? t('warez.menu.word.installed') : '' }))
                    : [],
            }),
        ),
    ];
    const installed: MenuRow[] = MENU_KINDS.map((kind) => {
        const entries = sources.installed[kind];
        return row({ scope: 'installed', page: 'kind', kind }, kindPlural(kind, t), 1, {
            kind,
            count: entries.length,
            zero: entries.length === 0,
            children: q
                ? entries.filter((entry) => matches(entry.title, q)).map((entry) => row({ scope: 'installed', page: 'item', kind, key: entry.key }, entry.title, 2, { word: entry.word }))
                : [],
        });
    });
    const look: MenuRow[] = sources.needs
        .filter((need) => need.count > 0)
        .sort((a, b) => LOOK_PAGES.indexOf(a.page) - LOOK_PAGES.indexOf(b.page))
        .map((need) => row({ scope: 'look', page: need.page }, t(`warez.menu.look.${need.page}`), 1, { count: need.count }));
    const groups: MenuGroup[] = readonly
        ? [{ id: 'store' as const, label: t('warez.menu.group.store'), rows: store }]
        : [
        ...(look.length ? [{ id: 'look' as const, label: t('warez.menu.group.look'), rows: look }] : []),
        { id: 'store', label: t('warez.menu.group.store'), rows: store },
        { id: 'installed', label: t('warez.menu.group.installed'), rows: installed },
        { id: 'yours', label: t('publish.new.menu_heading'), rows: [row({ scope: 'publish', page: 'tab', tab: 'submissions' }, t('publish.new.page_title'), 1, { icon: 'upload' })] },
    ];
    if (!q) return groups;
    return groups
        .map((group) => ({ ...group, rows: group.rows.map((r) => narrow(r, q)).filter((r): r is MenuRow => r !== null) }))
        .filter((group) => group.rows.length > 0);
}

export function nodeLabel(node: MenuNode, sources: MenuSources, t: Translate): string {
    if (node.scope === 'look') return t(`warez.menu.look.${node.page}`);
    if (node.scope === 'publish') return t('publish.new.page_title');
    if (node.page === 'item' && node.scope === 'store') return sources.storeItems.find((entry) => entry.id === node.id)?.title ?? node.id;
    if (node.page === 'item') return sources.installed[node.kind].find((entry) => entry.key === node.key)?.title ?? node.key;
    if (node.page === 'kind') return kindPlural(node.kind, t);
    return t(`warez.menu.${node.page}`);
}
