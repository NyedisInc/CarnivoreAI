
<script lang="ts">
    import type { Translate } from '../sessions/types';

    interface Props {
        verdict: 'clean' | 'flagged' | 'blocked' | 'unreadable';
        t: Translate;
        label?: string | null;
        shapeOnly?: boolean;
    }

    const { verdict, t, label = null, shapeOnly = false }: Props = $props();
    const word = $derived(label ?? t(`warez.verdict.${verdict}`));
</script>

<span class="verdict-mark verdict-mark--{verdict}" data-verdict={verdict}>
    <svg viewBox="0 0 10 10" aria-hidden="true" focusable="false">
        {#if verdict === 'clean'}
            <rect x="1" y="1" width="8" height="8" fill="currentColor" />
        {:else if verdict === 'flagged'}
            <path d="M1 1h5l3 3v5H1z" fill="currentColor" />
        {:else if verdict === 'blocked'}
            <rect x="1.5" y="1.5" width="7" height="7" fill="none" stroke="currentColor" stroke-width="1.2" />
            <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" stroke-width="1.2" />
        {:else}
            <rect x="1.5" y="1.5" width="7" height="7" fill="none" stroke="currentColor" stroke-width="1.2" />
            <path d="M3.5 5h3" stroke="currentColor" stroke-width="1.2" />
        {/if}
    </svg>
    {#if shapeOnly}
        <span class="verdict-mark__sr">{word}</span>
    {:else}
        <span class="verdict-mark__word">{word}</span>
    {/if}
</span>

<style>
    .verdict-mark {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
        font-size: 11px;
        color: var(--oc-text-secondary);
        white-space: nowrap;
    }

    .verdict-mark svg {
        width: 10px;
        height: 10px;
        flex: none;
    }

    .verdict-mark--clean,
    .verdict-mark--unreadable {
        color: var(--oc-text-secondary);
    }

    .verdict-mark--flagged {
        color: var(--oc-text-primary);
    }

    .verdict-mark--blocked {
        color: var(--oc-coral);
    }

    .verdict-mark__word {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .verdict-mark__sr {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip-path: inset(50%);
    }
</style>
