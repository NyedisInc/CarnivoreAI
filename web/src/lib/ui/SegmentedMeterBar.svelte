
<script lang="ts">
    interface Props {
        segments: number;
        filled: number;
        scale: number | null;
        meterText: string;
        height?: number;
        dim?: boolean;
        decorative?: boolean;
    }

    const { segments, filled, scale, meterText, height = 7, dim = false, decorative = false }: Props = $props();
</script>

<span
    class="seg-bar"
    class:seg-bar--dim={dim}
    data-scale={scale ?? ''}
    role={decorative ? undefined : 'img'}
    aria-label={decorative ? undefined : meterText}
    aria-hidden={decorative ? 'true' : undefined}
    style="--seg-bar-height: {height}px"
>
    {#each Array.from({ length: segments }, (_, i) => i) as i (i)}
        <span class="seg-bar__cell" data-on={i < filled ? '1' : '0'}></span>
    {/each}
</span>

<style>
    .seg-bar {
        display: flex;
        flex: 1 1 auto;
        min-width: 0;
        gap: 1px;
        height: var(--seg-bar-height, 7px);
        --seg-bar-fill: var(--oc-text-dim);
    }

    .seg-bar--dim {
        opacity: 0.55;
    }

    .seg-bar__cell {
        flex: 1 1 0;
        border-radius: 1px;
        box-shadow: inset 0 0 0 1px color-mix(in oklab, var(--seg-bar-fill) 45%, transparent);
    }

    .seg-bar__cell[data-on='1'] {
        background: var(--seg-bar-fill);
        box-shadow: none;
    }

    .seg-bar[data-scale='1'] {
        --seg-bar-fill: var(--oc-green-bright);
    }
    .seg-bar[data-scale='2'] {
        --seg-bar-fill: var(--oc-cyan);
    }
    .seg-bar[data-scale='3'] {
        --seg-bar-fill: var(--oc-yellow-bright);
    }
    .seg-bar[data-scale='4'] {
        --seg-bar-fill: color-mix(in oklab, var(--oc-yellow-bright) 55%, var(--oc-coral));
    }
    .seg-bar[data-scale='5'] {
        --seg-bar-fill: var(--oc-coral);
    }
</style>
