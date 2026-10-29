<!-- noopener noreferrer -->
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { CatalogCredit } from './catalog-plugins.svelte';
    import './catalog-plugins.css';

    interface Props {
        credit: CatalogCredit | null;
        t: Translate;
    }

    const { credit, t }: Props = $props();
</script>

{#if credit && (credit.sourceUrl || credit.publisher)}
    <div class="cpc" data-catalog-credit>
        {#if credit.sourceUrl}
            <a class="cpc__source" href={credit.sourceUrl} target="_blank" rel="noopener noreferrer">{t('plugins.page.credit.source')}</a>
        {/if}
        {#if credit.publisher}
            <span class="cpc__trust">{t('plugins.page.credit.distributed', { name: credit.publisher })}</span>
        {/if}
    </div>
{/if}
