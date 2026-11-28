
<script lang="ts">
    import IconButton from '../base/IconButton.svelte';

    interface Props {
        text: string;
        label: string;
    }

    const { text, label }: Props = $props();

    let open = $state(false);
    const noteId = `info-tip-${Math.random().toString(36).slice(2, 9)}`;
</script>

<span class="info-tip" data-open={open ? '1' : undefined}>
    <IconButton
        variant="secondary"
        label={label}
        tooltip={text}
        active={open}
        aria-expanded={open}
        aria-controls={noteId}
        data-info-tip-btn=""
        onclick={() => (open = !open)}
        onkeydown={(event) => {
            if (event.key === 'Escape' && open) {
                event.stopPropagation();
                open = false;
            }
        }}
    >i</IconButton>
    {#if open}
        <span class="info-tip__note" id={noteId} role="note">{text}</span>
    {/if}
</span>

<style>
  @layer components {
    .info-tip {
        display: inline-flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: var(--oc-space-2);
        min-width: 0;
    }

    .info-tip__note {
        min-width: 0;
        max-width: 60ch;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-hint);
        line-height: 1.5;
    }
  }
</style>
