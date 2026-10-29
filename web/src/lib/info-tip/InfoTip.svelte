
<script lang="ts">
    interface Props {
        text: string;
        label: string;
    }

    const { text, label }: Props = $props();

    let open = $state(false);
    const noteId = `info-tip-${Math.random().toString(36).slice(2, 9)}`;
</script>

<span class="info-tip" data-open={open ? '1' : undefined}>
    <button
        type="button"
        class="info-tip__btn"
        aria-label={label}
        aria-expanded={open}
        aria-controls={noteId}
        onclick={() => (open = !open)}
        onkeydown={(event) => {
            if (event.key === 'Escape' && open) {
                event.stopPropagation();
                open = false;
            }
        }}
    >i</button>
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

    .info-tip__btn {
        /* reserved 1px border */
        box-sizing: border-box;
        width: 16px;
        height: 16px;
        padding: 0;
        border: 1px solid var(--oc-line-panel);
        border-radius: var(--oc-radius-sm);
        background: transparent;
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: 10px;
        font-style: italic;
        line-height: 1;
        cursor: pointer;
    }

    .info-tip__btn:hover,
    .info-tip[data-open] .info-tip__btn {
        border-color: var(--oc-orange);
        color: var(--oc-orange);
    }

    .info-tip__note {
        min-width: 0;
        max-width: 60ch;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-hint);
        line-height: 1.5;
    }

    @media (max-width: 767px) {
        .info-tip__btn {
            width: var(--oc-tap, 28px);
            height: var(--oc-tap, 28px);
            font-size: 13px;
        }
    }
  }
</style>
