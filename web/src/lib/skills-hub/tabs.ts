import type { MenuNode, SkillsTab } from '../catalog/menu/route';

export type OldSkillsTab = 'installed' | 'census' | 'pack';

const NEW_TAB: Record<string, SkillsTab | undefined> = { census: 'stats', stats: 'stats', pack: 'pack' };

export function skillsNode(tab?: string | null): MenuNode {
    const mapped = tab ? NEW_TAB[tab] : undefined;
    return { scope: 'installed', page: 'kind', kind: 'skill', ...(mapped ? { tab: mapped } : {}) };
}
