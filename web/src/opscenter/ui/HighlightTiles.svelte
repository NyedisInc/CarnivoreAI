
<script lang="ts" module>
    export interface HighlightTile {
        readonly id: string;
        readonly name: string;
        readonly letter?: string;
        readonly figure: string;
        readonly unit: string;
        readonly line: string;
        readonly activity: readonly number[];
    }
</script>

<script lang="ts">
    import Sparkline from './Sparkline.svelte';

    interface Props {
        label?: string;
        caption?: string;
        tiles: readonly HighlightTile[];
        sparkLabel: string;
    }

    const { label = '', caption, tiles, sparkLabel }: Props = $props();
    const shown = $derived(tiles.slice(0, 5));
    const uid = `tiles-${Math.random().toString(36).slice(2, 9)}`;
</script>

<section class="oc-tiles" aria-labelledby={label ? `${uid}-label` : undefined} aria-label={label ? undefined : sparkLabel}>
    {#if label || caption}
        <div class="oc-kit-label" class:oc-kit-label--bare={!label}>
            {#if label}<h2 class="oc-kit-label__title" id="{uid}-label">{label}</h2>{/if}
            {#if caption}<span>{caption}</span>{/if}
        </div>
    {/if}
    <div class="oc-tiles__grid">
        {#each shown as tile, index (tile.id)}
            <article class="oc-tile" data-tile={tile.id}>
                <div class="oc-tile__head">
                    <span class="oc-icon-tile oc-tile__mark" style="--tile-size: 24px" aria-hidden="true">{(tile.letter ?? tile.name.charAt(0)).toUpperCase()}</span>
                    <h3 class="oc-tile__name">{tile.name}</h3>
                    <span class="oc-tile__rank">{String(index + 1).padStart(2, '0')}</span>
                </div>
                <div class="oc-tile__figure"><span class="oc-tile__value">{tile.figure}</span><span class="oc-tile__unit">{tile.unit}</span></div>
                <div class="oc-tile__line">{tile.line}</div>
                {#if tile.activity.length}
                    <div class="oc-tile__spark" role="img" aria-label={sparkLabel}>
                        <Sparkline values={[...tile.activity]} height={16} gap={1} tone="var(--oc-green)" />
                    </div>
                {/if}
            </article>
        {/each}
    </div>
</section>
