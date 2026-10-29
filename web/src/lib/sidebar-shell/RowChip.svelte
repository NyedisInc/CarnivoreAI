<!-- <button> -->
<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { RowChipSpec } from './row-plan';

    let { chip, lead, children }: { chip: RowChipSpec; lead?: Snippet; children?: Snippet } = $props();

    const tag = $derived(chip.attrs.type === 'button' ? 'button' : 'span');
</script>

<svelte:element this={tag} {...chip.attrs}>{@render lead?.()}{#if chip.svg}{@html chip.svg}{/if}{#if chip.text}{chip.text}{/if}{@render children?.()}</svelte:element>
