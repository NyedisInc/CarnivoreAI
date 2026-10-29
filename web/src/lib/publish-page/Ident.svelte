
<script lang="ts">
    import { identParts } from './report-format';

    const { text }: { text: string } = $props();
    const parts = $derived(identParts(text));
</script>

{#each parts as part, i (i)}{#if part.tok}<span class="pp-tok">{part.text}</span>{#if part.wbr}<wbr />{/if}{:else}{part.text}{/if}{/each}
