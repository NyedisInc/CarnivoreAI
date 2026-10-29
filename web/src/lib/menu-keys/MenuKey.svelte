
<script lang="ts">
    const { key }: { key: string } = $props();
</script>

{#if key}<kbd class="menu-key" aria-hidden="true">{key}</kbd>{/if}

<style>
    @layer components {
        .menu-key {
            flex: 0 0 auto;
            margin-left: auto;
            padding-left: var(--oc-space-3);
            color: var(--oc-text-dim);
            background: none;
            border: 0;
            font-family: var(--font-mono);
            font-size: var(--oc-fs-label);
            line-height: inherit;
            text-transform: lowercase;
        }
    }
</style>
