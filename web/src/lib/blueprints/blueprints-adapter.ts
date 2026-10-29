import type { ManagerAdapter, ManagerItem } from '../manager-frame/types';
import type { Translate } from '../sessions/types';
import { blueprintError, listBlueprints } from './api';
import { providerMark } from '../sessions/agent-marks';
import type { Blueprint } from './types';

export interface BlueprintItem extends ManagerItem {
    readonly blueprint: Blueprint;
}

const FAMILY_TAGS_SHOWN = 2;

export function familyTags(counts: readonly (readonly [string, number])[]): string[] {
    const shown = counts.slice(0, FAMILY_TAGS_SHOWN).map(([key, n]) => `${key} ${n}`);
    return counts.length > FAMILY_TAGS_SHOWN ? [...shown, `+${counts.length - FAMILY_TAGS_SHOWN}`] : shown;
}

/* running sessions */
export function toBlueprintItem(blueprint: Blueprint, t: Translate): BlueprintItem {
    const count = t('session.summary.sessions', { count: blueprint.spec.sessions.length });
    const counts = new Map<string, number>();
    const tileFamilies = new Map<string, string>();
    for (const session of blueprint.spec.sessions) {
        const key = providerMark(session.family).key;
        counts.set(key, (counts.get(key) ?? 0) + 1);
        if (!tileFamilies.has(key)) tileFamilies.set(key, session.family);
    }
    return {
        id: blueprint.blueprint_uuid,
        name: blueprint.name,
        meta: count,
        byline: count,
        iconFamilies: [...tileFamilies.values()],
        tags: familyTags([...counts]),
        blueprint,
    };
}

export function createBlueprintsAdapter(t: Translate, fetcher: typeof listBlueprints = listBlueprints): ManagerAdapter {
    return {
        async list(): Promise<readonly ManagerItem[]> {
            let result;
            try {
                result = await fetcher();
            } catch (err) {
                throw new Error(blueprintError(err).detail);
            }
            if (result.status !== 'ok') throw new Error(result.detail ?? '');
            return result.blueprints.map((blueprint) => toBlueprintItem(blueprint, t));
        },
    };
}
