import type { ManagerAdapter, ManagerItem } from '../manager-frame/types';
import type { Translate } from '../sessions/types';
import { authFetch } from '../../opscenter/api/auth.svelte';
import { fetchInventory, putOverride, refusalOf, type Fetcher } from './skills-api';
import { planWrites, toItems, type ContextChoice } from './skills-model';
import type { Inventory, OverrideResult } from './skills-types';

export interface SkillsAdapterHooks {
    onInventory: (inventory: Inventory) => void;
    onWrote: (result: OverrideResult) => void;
    onWriting: () => void;
}

export function createSkillsAdapter(
    t: Translate,
    context: () => ContextChoice,
    hooks: SkillsAdapterHooks,
    fetcher: Fetcher = authFetch,
): ManagerAdapter {
    let last: Inventory | null = null;

    async function read(): Promise<Inventory> {
        const now = context();
        last = await fetchInventory({ projectPath: now.projectPath, profile: now.profile }, fetcher).catch((error) => {
            throw new Error(refusalOf(error, t('skills.page.error')));
        });
        hooks.onInventory(last);
        return last;
    }

    return {
        async list(): Promise<readonly ManagerItem[]> {
            return toItems(await read(), context(), t);
        },
        async setEnabled(id: string, enabled: boolean): Promise<ManagerItem> {
            const now = context();
            const group = last?.skills.find((g) => g.name === id);
            if (!group) throw new Error(t('skills.page.error_gone', { name: id }));
            for (const write of planWrites(group, now, enabled ? 'on' : 'off')) {
                hooks.onWriting();
                try {
                    const result = await putOverride(
                        {
                            harness: write.harness,
                            file: write.file,
                            skill: id,
                            state: write.state,
                            projectPath: now.projectPath,
                            profile: now.profile,
                        },
                        fetcher,
                    );
                    hooks.onWrote(result);
                } catch (error) {
                    throw new Error(refusalOf(error, t('skills.page.error_write')));
                }
            }
            const items = toItems(await read(), now, t);
            const item = items.find((candidate) => candidate.id === id);
            if (!item) throw new Error(t('skills.page.error_gone', { name: id }));
            return item;
        },
    };
}
