<!-- could not be read -->
<script lang="ts" module>
export interface RailRow {
    id: string;
    label: string;
    count: number;
    on: boolean;
    mark?: { letter: string; place: string };
    glyph?: string;
}
</script>

<script lang="ts">
    import type { Translate } from '../sessions/types';
    import GroupGlyph from './GroupGlyph.svelte';

    interface Props {
        groups: readonly RailRow[];
        fits: readonly RailRow[];
        states: readonly RailRow[];
        busy: boolean;
        t: Translate;
        onPick: (group: 'group' | 'place' | 'st', id: string) => void;
    }

    const { groups, fits, states, busy, t, onPick }: Props = $props();

    const sets = $derived([
        { key: 'group' as const, label: t('widgets.places.rail.groups'), rows: groups },
        { key: 'place' as const, label: t('widgets.places.rail.fits'), rows: fits },
        { key: 'st' as const, label: t('widgets.places.rail.state'), rows: states },
    ]);
</script>

<nav class="wp-rail" aria-label={t('widgets.places.rail.label')}>
    {#each sets as set (set.key)}
        <div class="wp-rail__group" role="radiogroup" aria-label={set.label} data-group={set.key}>
            <span class="wp-rail__label">{set.label}</span>
            {#each set.rows as row (row.id)}
                <button type="button" class="wp-rail__row" role="radio" aria-checked={row.on} disabled={busy} data-rail={`${set.key}:${row.id}`} onclick={() => onPick(set.key, row.id)}>
                    {#if row.mark}<span class="wp-pmark" data-pl={row.mark.place}>{row.mark.letter}</span>{:else if row.glyph}<GroupGlyph name={row.glyph} />{/if}
                    <span class="wp-rail__text">{row.label}</span>
                    <span class="wp-rail__count">{row.count}</span>
                </button>
            {/each}
        </div>
    {/each}
</nav>
