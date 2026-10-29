
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { LEDGER_KEYS } from './ledger-model';

    interface Props {
        color: string | null;
        name: string;
        busy: boolean;
        editing: boolean;
        onEdit?: () => void;
        t: Translate;
    }

    const { color, name, busy, editing, onEdit, t }: Props = $props();
</script>

<span class="ledger-mark-cell">
    {#if onEdit}
        <button
            type="button"
            class="ledger-mark"
            class:ledger-mark--none={color === null}
            style="--mark: {color ?? 'transparent'}"
            aria-expanded={editing}
            aria-label={t(LEDGER_KEYS.editOpen, { name })}
            title={t(LEDGER_KEYS.editOpen, { name })}
            disabled={busy}
            onclick={onEdit}
        ></button>
    {:else}
        
        <span
            class="ledger-mark ledger-mark--flat"
            class:ledger-mark--none={color === null}
            style="--mark: {color ?? 'transparent'}"
            aria-hidden="true"
        ></span>
    {/if}
</span>

<style>
    .ledger-mark-cell {
        position: relative;
        display: inline-flex;
        align-items: center;
    }

    .ledger-mark {
        width: 12px;
        height: 12px;
        padding: 0;
        border-radius: 2px;
        border: 1px solid var(--oc-line-rule);
        background: var(--mark);
        cursor: pointer;
    }

    .ledger-mark--none {
        background: transparent;
        border-style: dashed;
    }

    .ledger-mark--flat {
        display: inline-block;
        cursor: default;
    }

    .ledger-mark:hover:not(:disabled) {
        border-color: var(--oc-cyan);
    }

    .ledger-mark:disabled {
        opacity: 0.6;
        cursor: default;
    }

    @media (max-width: 1023px) {
        .ledger-mark {
            width: 18px;
            height: 18px;
        }
    }
</style>
