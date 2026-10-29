import type { Translate } from '../sessions/types';
import { AUTOPSY_CAP, NO_HEALTH, ledgerRowsOf, tripwireOf, type SkillHealthMap, type Tripwire } from './skill-state';
import { fetchCensus, fetchLedger, putOverride, refusalCode, refusalOf, removeLocation, skillHost, type Fetcher } from './skills-api';
import { planWrites, type ContextChoice, type SkillItem } from './skills-model';
import type { Inventory, OverrideResult, SkillLocationRow } from './skills-types';

export interface RemovalState {
    readonly busy: boolean;
    readonly error: string | null;
}

export function createSkillActions(o: {
    fetcher: Fetcher;
    t: Translate;
    context: () => ContextChoice;
    inventory: () => Inventory | null;
    reload: () => Promise<unknown>;
    onWriting?: () => void;
    onWrote?: (result: OverrideResult) => void;
}): {
    readonly writing: readonly string[];
    readonly writeError: string | null;
    readonly removals: Readonly<Record<string, RemovalState>>;
    readonly health: SkillHealthMap;
    changeState(item: SkillItem, harness: 'claude' | 'codex', choice: string): Promise<void>;
    remove(location: SkillLocationRow): Promise<void>;
    loadHealth(next: Inventory): Promise<void>;
    clearError(): void;
} {
    const { fetcher, t, context, inventory, reload, onWriting, onWrote } = o;
    let writing = $state<string[]>([]);
    let writeError = $state<string | null>(null);
    let removals = $state<Record<string, RemovalState>>({});
    let health = $state<SkillHealthMap>(NO_HEALTH);
    let healthRun = 0;

    return {
        get writing() { return writing; },
        get writeError() { return writeError; },
        get removals() { return removals; },
        get health() { return health; },
        clearError(): void {
            writeError = null;
        },
        async loadHealth(next): Promise<void> {
            const run = (healthRun += 1);
            const now = context();
            const ask = { projectPath: now.projectPath, profile: now.profile };
            const [ledger, measured] = await Promise.all([fetchLedger(fetcher), fetchCensus(ask, fetcher).catch(() => null)]);
            const managed = next.skills.filter((g) => ledgerRowsOf(g, ledger).length > 0).slice(0, AUTOPSY_CAP);
            const host = skillHost(fetcher);
            const judged = await Promise.all(
                managed.map(async (g): Promise<[string, Tripwire]> => {
                    const autopsy = await host.skillAutopsy?.(g.name).catch(() => null);
                    return [g.name, tripwireOf(autopsy ?? null)];
                }),
            );
            if (run !== healthRun) return;
            health = { ledger, census: measured, tripwire: Object.fromEntries(judged) };
        },
        async changeState(item, harness, choice): Promise<void> {
            const group = inventory()?.skills.find((g) => g.name === item.id);
            if (!group) return;
            const now = context();
            writeError = null;
            writing = [...writing, harness];
            try {
                for (const write of planWrites(group, now, choice, harness)) {
                    onWriting?.();
                    const result = await putOverride(
                        { harness: write.harness, file: write.file, skill: item.id, state: write.state, projectPath: now.projectPath, profile: now.profile },
                        fetcher,
                    );
                    onWrote?.(result);
                }
            } catch (error) {
                writeError = refusalOf(error, t('skills.page.error_write'));
            } finally {
                writing = writing.filter((h) => h !== harness);
                onWriting?.();
                void reload();
            }
        },
        async remove(location): Promise<void> {
            const id = location.location_id;
            const now = context();
            removals = { ...removals, [id]: { busy: true, error: null } };
            try {
                await removeLocation(id, { projectPath: now.projectPath, profile: now.profile }, fetcher);
                const { [id]: _done, ...rest } = removals;
                removals = rest;
                onWriting?.();
                await reload();
            } catch (error) {
                const message = refusalCode(error) === 'use_catalog_uninstall' ? t('skills.loc.catalog_managed') : refusalOf(error, t('skills.page.error'));
                removals = { ...removals, [id]: { busy: false, error: message } };
            }
        },
    };
}
