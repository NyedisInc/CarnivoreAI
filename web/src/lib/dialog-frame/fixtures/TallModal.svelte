
<script lang="ts">
    import ModalShell from '../ModalShell.svelte';

    const { rows = 40 }: { rows?: number } = $props();
</script>

<ModalShell title="approve" look="titlerow" onCancel={() => {}} data-tall-modal="">
    {#each Array.from({ length: rows }, (_, i) => i) as row (row)}
        <p data-tall-row={row}>permission {row}</p>
    {/each}
    {#snippet footer()}
        <button type="button" data-tall-approve="">approve</button>
    {/snippet}
</ModalShell>
