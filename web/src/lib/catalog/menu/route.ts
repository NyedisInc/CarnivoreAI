
export const MENU_KINDS = ['skill', 'theme', 'mod', 'plugin'] as const;
export type MenuKind = (typeof MENU_KINDS)[number];

export const SKILLS_TABS = ['stats', 'pack'] as const;
export type SkillsTab = (typeof SKILLS_TABS)[number];

export const LOOK_PAGES = ['consent', 'flagged', 'settings', 'updates'] as const;
export type LookPage = (typeof LOOK_PAGES)[number];

export const PUBLISH_TABS = ['submissions', 'skills', 'themes', 'mods', 'plugins'] as const;
export type PublishTab = (typeof PUBLISH_TABS)[number];

export type MenuNode =
    | { scope: 'store'; page: 'everything' | 'newest' | 'updates' }
    | { scope: 'store'; page: 'kind'; kind: MenuKind }
    | { scope: 'store'; page: 'item'; id: string }
    | { scope: 'installed'; page: 'kind'; kind: MenuKind; tab?: SkillsTab }
    | { scope: 'installed'; page: 'item'; kind: MenuKind; key: string; tab?: string }
    | { scope: 'look'; page: LookPage }
    | { scope: 'publish'; page: 'tab'; tab: PublishTab }
    | { scope: 'publish'; page: 'item'; tab: PublishTab; location: string; event?: string }
    | { scope: 'publish'; page: 'rules' };

export const RESERVED_SEGMENTS: readonly string[] = ['store', 'installed', 'look', 'publish'];

export const HOME_NODE: MenuNode = { scope: 'store', page: 'everything' };

const PLURAL: Record<MenuKind, string> = { skill: 'skills', theme: 'themes', mod: 'mods', plugin: 'plugins' };

function kindOfSegment(segment: string | undefined): MenuKind | null {
    return MENU_KINDS.find((kind) => kind === segment || PLURAL[kind] === segment) ?? null;
}

export function parseNodeHash(hash: string | null | undefined): MenuNode | null {
    if (typeof hash !== 'string') return null;
    const match = /^#?warez\/(.+)$/.exec(hash.trim());
    if (!match) return null;
    let parts: string[];
    try {
        parts = (match[1] ?? '').split('/').filter(Boolean).map((part) => decodeURIComponent(part));
    } catch {
        return null;
    }
    const [scope, second, third, fourth] = parts;
    if (scope === 'store') {
        if (second === 'everything' || second === 'newest' || second === 'updates') return { scope: 'store', page: second };
        const kind = kindOfSegment(second);
        return kind ? { scope: 'store', page: 'kind', kind } : null;
    }
    if (scope === 'installed') {
        const kind = kindOfSegment(second);
        if (!kind) return null;
        if (!third) return { scope: 'installed', page: 'kind', kind };
        if (second === 'skills' && !fourth && (SKILLS_TABS as readonly string[]).includes(third)) return { scope: 'installed', page: 'kind', kind, tab: third as SkillsTab };
        return { scope: 'installed', page: 'item', kind, key: third, ...(fourth ? { tab: fourth } : {}) };
    }
    if (scope === 'publish') {
        if (second === 'rules') return { scope: 'publish', page: 'rules' };
        const tab = (PUBLISH_TABS as readonly string[]).includes(second ?? '') ? (second as PublishTab) : 'submissions';
        return third ? { scope: 'publish', page: 'item', tab, location: third, ...(fourth ? { event: fourth } : {}) } : { scope: 'publish', page: 'tab', tab };
    }
    if (scope === 'look' && (LOOK_PAGES as readonly string[]).includes(second ?? '')) return { scope: 'look', page: second as LookPage };
    return null;
}

export function nodeHash(node: MenuNode): string {
    if (node.scope === 'publish') {
        if (node.page === 'rules') return '#warez/publish/rules';
        if (node.page === 'tab') return node.tab === 'submissions' ? '#warez/publish' : `#warez/publish/${node.tab}`;
        return `#warez/publish/${node.tab}/${encodeURIComponent(node.location)}${node.event ? `/${encodeURIComponent(node.event)}` : ''}`;
    }
    if (node.scope === 'look') return `#warez/look/${node.page}`;
    if (node.page === 'item' && node.scope === 'store') return `#warez/${node.id.split('/').map(encodeURIComponent).join('/')}`;
    if (node.page === 'kind') return `#warez/${node.scope}/${PLURAL[node.kind]}${node.scope === 'installed' && node.tab ? `/${node.tab}` : ''}`;
    if (node.page === 'item') {
        const tab = node.tab && node.tab !== 'overview' ? `/${encodeURIComponent(node.tab)}` : '';
        return `#warez/installed/${node.kind}/${encodeURIComponent(node.key)}${tab}`;
    }
    return `#warez/${node.scope}/${node.page}`;
}

export function nodeKey(node: MenuNode): string {
    if (node.scope === 'publish') return 'publish';
    if (node.scope === 'installed' && node.page === 'kind') return nodeHash({ scope: 'installed', page: 'kind', kind: node.kind }).replace(/^#warez\//, '');
    return nodeHash(node).replace(/^#warez\//, '');
}
