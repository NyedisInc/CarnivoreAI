
<script lang="ts">
    interface Props {
        state: string;
        word: string;
        showWord?: boolean;
    }

    const { state, word, showWord = false }: Props = $props();
</script>

<span class="ph-mark" title={showWord ? undefined : word}>
    <span class="ph-led ph-led--{state}" aria-hidden="true"></span>
    {#if showWord}<span class="ph-word ph-word--{state}">{word}</span>{:else}<span class="oc-visually-hidden">{word}</span>{/if}
</span>

<style>
    @layer components {
        .ph-mark {
            display: inline-flex;
            align-items: center;
            gap: var(--oc-space-2);
            min-width: 0;
        }
    }
</style>
