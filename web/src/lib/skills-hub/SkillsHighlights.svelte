
<script lang="ts">
    import HighlightTiles, { type HighlightTile } from '../../opscenter/ui/HighlightTiles.svelte';
    import type { Translate } from '../sessions/types';
    import type { Census } from '../skills-page/skills-types';
    import { topFired } from './highlights';

    interface Props {
        census: Census | null;
        t: Translate;
    }

    const { census, t }: Props = $props();

    const tiles = $derived<HighlightTile[]>(
        topFired(census, 'd30').map((row) => ({
            id: row.name,
            name: row.name,
            figure: String(row.fires.d30),
            unit: t('skills.census.fires'),
            line: t('skills.hub.hl.line', { d7: row.fires.d7, d90: row.fires.d90 }),
            activity: [],
        })),
    );
</script>

{#if tiles.length > 0}
    <div class="sk-hl" data-skills-highlights>
        <HighlightTiles label={t('skills.hub.hl.top')} caption={t('skills.hub.hl.top_caption')} {tiles} sparkLabel={t('skills.hub.hl.top')} />
    </div>
{/if}

<style>
    .sk-hl {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-3);
        margin-bottom: var(--oc-space-4, 16px);
        min-width: 0;
    }
</style>
