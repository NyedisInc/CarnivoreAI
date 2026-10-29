
<script lang="ts">
    import type { Snippet } from 'svelte';

    interface Props {
        label: string;
        caption?: string;
        first: Snippet;
        second: Snippet;
    }

    const { label, caption, first, second }: Props = $props();
    const uid = `pair-${Math.random().toString(36).slice(2, 9)}`;
</script>

<section class="oc-pair" aria-labelledby="{uid}-label">
    <div class="oc-kit-label">
        <h2 class="oc-kit-label__title" id="{uid}-label">{label}</h2>
        {#if caption}<span>{caption}</span>{/if}
    </div>
    <div class="oc-pair__grid">{@render first()}{@render second()}</div>
</section>
