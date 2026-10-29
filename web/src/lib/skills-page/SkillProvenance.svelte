
<script lang="ts">
    import CostBadge from '../catalog/CostBadge.svelte';
    import DeprecatedMark from '../catalog/DeprecatedMark.svelte';
    import TrustBlock from '../catalog/TrustBlock.svelte';
    import { cardView, latestVersion } from '../catalog/card';
    import type { CatalogItem, InstalledItem } from '../catalog/types';
    import type { Translate } from '../sessions/types';
    import { fetchCatalogEntry, type Fetcher } from './skills-api';

    function consentLabel(via: string): string {
        if (via === 'sheet') return t('skills.prov.consent_sheet');
        if (via === 'one_click') return t('skills.prov.consent_one_click');
        if (via === 'blueprint') return t('skills.prov.consent_blueprint');
        if (via === 'pack') return t('skills.prov.consent_pack');
        return via;
    }

    interface Props {
        ledger: readonly InstalledItem[];
        itemId: string | null;
        fetcher: Fetcher;
        t: Translate;
    }

    const { ledger, itemId, fetcher, t }: Props = $props();

    let entry = $state<CatalogItem | null>(null);
    let settled = $state(false);

    $effect(() => {
        const id = itemId;
        entry = null;
        settled = id === null;
        let cancelled = false;
        if (id !== null) {
            void fetchCatalogEntry(id, fetcher).then((answer) => {
                if (cancelled) return;
                entry = answer;
                settled = true;
            });
        }
        return () => {
            cancelled = true;
        };
    });

    const version = $derived(latestVersion(entry));
    const card = $derived(cardView(entry, false));
</script>

<div class="sk-prov" data-skill-provenance>
    {#each ledger as row (row.install_id)}
        <dl class="mgr-facts" data-install-facts={row.install_id}>
            <dt>{t('skills.prov.version')}</dt>
            <dd>{row.version ?? ''}</dd>
            <dt>{t('skills.prov.scope')}</dt>
            <dd>{row.scope === 'project' ? t('skills.prov.scope_project', { path: row.project_path ?? '' }) : t('skills.prov.scope_global')}</dd>
            {#if typeof row.consent_via === 'string'}
                <dt>{t('skills.prov.consent')}</dt>
                <dd>{consentLabel(row.consent_via)}</dd>
            {/if}
            {#if typeof row.update_available === 'boolean'}
                <dt>{t('skills.prov.update')}</dt>
                <dd data-skill-update>
                    {row.update_available ? t('skills.prov.update_available', { latest: row.latest_version ?? '' }) : t('skills.prov.up_to_date')}
                </dd>
            {/if}
            {#if typeof row.auto_update === 'boolean'}
                <dt>{t('skills.prov.auto_update')}</dt>
                <dd>{row.auto_update ? t('skills.prov.on') : t('skills.prov.off')}</dd>
            {/if}
        </dl>
    {/each}
    {#if itemId !== null}
        {#if entry}
            {#if card.deprecated}<DeprecatedMark supersededBy={card.supersededBy} {t} />{/if}
            <TrustBlock {version} {t} />
            <CostBadge item={entry} {t} />
        {:else if settled}
            <p class="sk-note" data-skill-no-entry>{t('skills.prov.no_entry')}</p>
        {/if}
    {:else}
        <p class="sk-note" data-skill-local>{t('skills.prov.local')}</p>
    {/if}
</div>
