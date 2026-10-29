
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { Translate } from '../sessions/types';
    import { compatView } from './compat';
    import type { CatalogItem } from './types';

    interface Props {
        item: CatalogItem | null;
        t: Translate;
    }

    const { item, t }: Props = $props();

    const view = $derived(compatView(item));
</script>

<section class="cat-compat" aria-label={t(BROWSE_KEYS.compatHeading)}>
    <span class="cat-compat__heading">{t(BROWSE_KEYS.compatHeading)}</span>
    {#if view.harnesses.length}
        <div class="cat-compat__badges">
            
            {#each view.harnesses as name}
                <span class="cat-compat__badge">{name}</span>
            {/each}
        </div>
    {:else}
        <p class="cat-compat__note">{t(BROWSE_KEYS.compatNone)}</p>
    {/if}
    {#if view.tools.length}
        <p class="cat-compat__note cat-compat__mono">
            {t(BROWSE_KEYS.compatTools, { tools: view.tools.join(', ') })}
        </p>
    {/if}
</section>

<style>
    .cat-compat {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .cat-compat__heading {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-compat__badges {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
    }

    .cat-compat__badge {
        padding: 1px 6px;
        border: 1px solid var(--cat-line);
        border-radius: 3px;
        color: var(--cat-text);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-compat__note {
        margin: 0;
        color: var(--cat-muted);
        font-size: 12px;
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    .cat-compat__mono {
        font-family: var(--cat-mono);
        font-size: 11px;
    }
</style>
