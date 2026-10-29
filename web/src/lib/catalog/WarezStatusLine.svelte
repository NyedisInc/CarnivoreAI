
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { CatalogIndexState } from './types';

    interface Props {
        index: CatalogIndexState | null;
        loading: boolean;
        wrap?: boolean;
        t: Translate;
    }

    const { index, loading, wrap = false, t }: Props = $props();

    const serial = $derived(typeof index?.serial === 'number' ? String(index.serial) : '-');
    const refusal = $derived.by((): string | null => {
        const found = index?.refusal as { code?: unknown } | null | undefined;
        return found && typeof found.code === 'string' ? found.code : null;
    });
    const tone = $derived<'loading' | 'refused' | 'degraded' | 'stale' | 'plain'>(
        loading && !index ? 'loading' : refusal !== null ? 'refused' : index?.degraded === true ? 'degraded' : index?.stale === true ? 'stale' : 'plain',
    );
</script>

{#if tone !== 'plain'}
<span class="warez-stat" class:warez-stat--stale={tone === 'stale'} class:warez-stat--degraded={tone === 'degraded'} class:warez-stat--refused={tone === 'refused'} class:warez-stat--wrap={wrap}>
    {#if tone === 'loading'}
        {t('warez.status.reading')}
    {:else if tone === 'refused'}
        <b>{t('warez.status.refused_tail', { code: refusal })}</b> &middot; {t('warez.status.last_good')}
    {:else if tone === 'degraded'}
        {t('warez.status.serial', { serial })} &middot; <b>{t('opscenter.catalog.index_degraded')}</b>
    {:else if tone === 'stale'}
        {t('warez.status.serial', { serial })} &middot; <b>{t('opscenter.catalog.index_stale')}</b>
    {/if}
</span>
{/if}

<style>
    .warez-stat {
        min-width: 0;
        overflow: hidden;
        color: var(--oc-text-muted);
        font-size: 11px;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .warez-stat--wrap {
        display: block;
        line-height: 1.4;
        white-space: normal;
    }

    .warez-stat b {
        font-weight: 400;
    }

    .warez-stat--stale b,
    .warez-stat--degraded b {
        color: var(--oc-yellow);
    }

    .warez-stat--refused b {
        color: var(--oc-coral);
    }
</style>
