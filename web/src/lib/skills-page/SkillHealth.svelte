
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import AutopsyFacts from '../catalog/AutopsyFacts.svelte';
    import DriftFacts from '../catalog/DriftFacts.svelte';
    import type { CatalogHost } from '../catalog/catalog';
    import type { InstalledItem } from '../catalog/types';
    import type { Translate } from '../sessions/types';
    import { refusalOf, restoreInstall, setInstallFork, type Fetcher } from './skills-api';
    import type { Tripwire } from './skill-state';

    interface Props {
        name: string;
        ledger: readonly InstalledItem[];
        tripwire: Tripwire | undefined;
        host: Pick<CatalogHost, 'skillAutopsy'>;
        fetcher: Fetcher;
        t: Translate;
        onChanged: () => void;
        onOpenCatalog: () => void;
    }

    const { name, ledger, tripwire, host, fetcher, t, onChanged, onOpenCatalog }: Props = $props();

    let asking = $state<string | null>(null);
    let working = $state<string | null>(null);
    let error = $state<string | null>(null);

    const judged = $derived(tripwire ?? { state: 'not_judged' as const });

    async function restore(row: InstalledItem): Promise<void> {
        const id = row.install_id;
        if (!id || typeof row.revision !== 'number') return;
        asking = null;
        working = id;
        error = null;
        try {
            await restoreInstall(id, row.revision, fetcher);
            onChanged();
        } catch (failure) {
            error = refusalOf(failure, t('skills.page.error_write'));
        } finally {
            working = null;
        }
    }

    async function fork(row: InstalledItem, next: boolean): Promise<void> {
        const id = row.install_id;
        if (!id) return;
        working = id;
        error = null;
        try {
            await setInstallFork(id, next, fetcher);
            onChanged();
        } catch (failure) {
            error = refusalOf(failure, t('skills.page.error_write'));
        } finally {
            working = null;
        }
    }
</script>

<div class="sk-health" data-skill-health>
    {#if ledger.length === 0}
        <p class="sk-note" data-skill-no-drift>{t('skills.health.no_ledger')}</p>
    {/if}
    {#each ledger as row (row.install_id)}
        <div class="sk-health__row" data-install={row.install_id}>
            <DriftFacts installed={row} {t} />
            {#if row.drift?.state === 'drifted' || row.forked}
                <div class="mgr-actions__row">
                    {#if row.drift?.state === 'drifted' && asking !== row.install_id}
                        <button
                            type="button"
                            class="oc-btn"
                            data-skill-restore
                            disabled={working === row.install_id}
                            onclick={() => (asking = row.install_id ?? null)}
                            >{working === row.install_id ? t(BROWSE_KEYS.driftRestoreWorking) : t(BROWSE_KEYS.driftRestore)}</button
                        >
                    {/if}
                    <button
                        type="button"
                        class="oc-btn"
                        data-skill-fork
                        disabled={working === row.install_id}
                        onclick={() => void fork(row, !row.forked)}
                        >{row.forked ? t(BROWSE_KEYS.driftForkClear) : t(BROWSE_KEYS.driftForkMark)}</button
                    >
                    <button type="button" class="oc-btn" onclick={onOpenCatalog}>{t('skills.loc.open_catalog')}</button>
                </div>
                {#if asking === row.install_id}
                    <p class="oc-notice oc-notice--error" role="alert" data-mgr-question>{t(BROWSE_KEYS.driftRestoreLead, { version: row.version ?? '' })}</p>
                    <div class="mgr-actions__row">
                        <button type="button" class="oc-btn oc-btn--danger" data-skill-restore-confirm onclick={() => void restore(row)}
                            >{t(BROWSE_KEYS.driftRestoreConfirm)}</button
                        >
                        <button type="button" class="oc-btn" onclick={() => (asking = null)}>{t('skills.loc.remove_cancel')}</button>
                    </div>
                {/if}
            {/if}
        </div>
    {/each}
    {#if error}<p class="oc-notice oc-notice--error" role="alert" data-mgr-error>{error}</p>{/if}

    <section class="sk-tripwire" aria-label={t('skills.health.tripwire')} data-tripwire={judged.state}>
        <span class="sk-tripwire__heading">{t('skills.health.tripwire')}</span>
        <p class="sk-tripwire__fact" class:sk-tripwire__fact--bad={judged.state === 'flagged'}>
            {judged.state === 'flagged'
                ? t('skills.health.tripwire_flagged', { categories: judged.categories.map((c) => c.replace(/_/g, ' ')).join(', ') })
                : judged.state === 'clean'
                  ? t('skills.health.tripwire_clean')
                  : t('skills.health.tripwire_not_judged')}
        </p>
    </section>

    <AutopsyFacts skill={name} {host} {t} />
</div>
