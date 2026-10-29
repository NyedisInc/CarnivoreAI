<!-- hidden -->
<script lang="ts">
    import type { Snippet } from 'svelte';

    interface Props {
        width: number;
        live?: boolean;
        children: Snippet;
    }

    const { width, live = false, children }: Props = $props();

    let box = $state<HTMLElement | null>(null);
    let inner = $state<HTMLElement | null>(null);
    let scale = $state(0.3);
    let height = $state(0);
    let boxWidth = $state(0);

    function measure(): void {
        if (!box || !inner) return;
        const w = box.clientWidth;
        boxWidth = w;
        if (w > 0) scale = Math.min(1, w / width);
        height = Math.ceil(inner.offsetHeight * scale);
    }

    $effect(() => {
        measure();
        if (!box || typeof ResizeObserver === 'undefined') return;
        const watch = new ResizeObserver(measure);
        watch.observe(box);
        if (inner) watch.observe(inner);
        return () => watch.disconnect();
    });
</script>

<div class="scaled oc-well" bind:this={box} style:height={height ? `${height}px` : undefined} aria-hidden={live ? undefined : 'true'}>
    <div class="scaled__in" class:scaled__in--live={live} bind:this={inner} style:width="{scale >= 1 ? Math.max(width, boxWidth) : width}px" style:transform="scale({scale})">
        {@render children()}
    </div>
</div>

<style>
    .scaled {
        position: relative;
        background: var(--oc-ground-page);
    }

    .scaled__in {
        position: absolute;
        left: 0;
        top: 0;
        transform-origin: 0 0;
        pointer-events: none;
    }

    .scaled__in--live {
        pointer-events: auto;
    }
</style>
