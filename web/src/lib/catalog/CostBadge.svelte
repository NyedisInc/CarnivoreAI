
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { Translate } from '../sessions/types';
    import { costView } from './cost';
    import type { CatalogItem } from './types';

    interface Props {
        item: CatalogItem | null;
        total?: number | null;
        line?: boolean;
        t: Translate;
    }

    const { item, total = null, line = false, t }: Props = $props();

    const view = $derived(costView(item));
</script>

{#if view && line && view.desc !== null && view.body !== null}
    <div class="cat-cost__line">{t('warez.detail.cost', { desc: view.desc, body: view.body })}</div>
    {#if total !== null}
        <div class="cat-cost__line">{t(BROWSE_KEYS.costTotal, { count: total })}</div>
    {/if}
{:else if view}
    <section class="cat-cost" aria-label={t(BROWSE_KEYS.costHeading)}>
        <span class="cat-cost__heading">{t(BROWSE_KEYS.costHeading)}</span>
        <ul class="cat-cost__facts">
            {#if view.desc !== null}
                <li class="cat-cost__fact">{t(BROWSE_KEYS.costDesc, { count: view.desc })}</li>
            {/if}
            {#if view.body !== null}
                <li class="cat-cost__fact">{t(BROWSE_KEYS.costBody, { count: view.body })}</li>
            {/if}
            {#if total !== null}
                <li class="cat-cost__fact cat-cost__total">{t(BROWSE_KEYS.costTotal, { count: total })}</li>
            {/if}
        </ul>
    </section>
{/if}

<style>
    .cat-cost__line {
        color: var(--oc-text-muted);
        font-size: 11px;
        overflow-wrap: anywhere;
    }

    .cat-cost {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .cat-cost__heading {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-cost__facts {
        display: flex;
        flex-direction: column;
        gap: 2px;
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .cat-cost__fact {
        color: var(--cat-text);
        font-family: var(--cat-mono);
        font-size: 11px;
    }

    .cat-cost__total {
        color: var(--cat-muted);
    }
</style>
