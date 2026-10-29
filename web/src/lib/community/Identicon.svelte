
<script lang="ts">
    import { GRID, identicon } from './identicon';

    interface Props {
        handle: string;
        size?: number;
    }

    const { handle, size = 20 }: Props = $props();
    const shape = $derived(identicon(handle));
</script>

<svg
    class="ident ident--{shape.tone}"
    data-tone={shape.tone}
    width={size}
    height={size}
    viewBox="0 0 {GRID} {GRID}"
    aria-hidden="true"
    focusable="false"
    shape-rendering="crispEdges"
>
    {#each shape.cells as [x, y]}
        <rect {x} {y} width="1" height="1" />
    {/each}
</svg>

<style>
  @layer components {
    .ident {
        flex-shrink: 0;
        border: 1px solid var(--oc-line-rule);
        background: var(--oc-ground-raised);
    }
    :global(.ident rect) { fill: var(--oc-orange); }
    :global(.ident--1 rect) { fill: var(--oc-cyan, var(--oc-orange)); }
    :global(.ident--2 rect) { fill: var(--oc-green, var(--oc-orange)); }
    :global(.ident--3 rect) { fill: var(--oc-yellow, var(--oc-orange)); }
  }
</style>
