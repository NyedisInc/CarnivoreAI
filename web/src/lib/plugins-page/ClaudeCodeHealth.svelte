
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import PluginHealthLine from './PluginHealthLine.svelte';
    import type { HealthRow } from './plugin-health';

    interface Props {
        rows: readonly HealthRow[];
        canAct: (row: HealthRow) => boolean;
        onAct: (row: HealthRow) => void;
        t: Translate;
    }

    const { rows, canAct, onAct, t }: Props = $props();
</script>

{#if rows.length}
    <section class="plp-region" aria-label={t('plugins.page.catalog.health.label')} data-claude-code-health>
        <h3 class="pl-label">{t('plugins.page.catalog.health.label')}</h3>
        {#each rows as row (row.id)}
            <PluginHealthLine {row} label={row.id} canAct={canAct(row)} onAct={() => onAct(row)} {t} />
        {/each}
    </section>
{/if}
