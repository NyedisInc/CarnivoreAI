
<script lang="ts">
    import Button from '../base/Button.svelte';
    import type { Translate } from '../sessions/types';
    import { LEDGER_KEYS } from './ledger-model';

    interface Props {
        adding: boolean;
        onAdd: () => void;
        t: Translate;
    }

    const { adding, onAdd, t }: Props = $props();
</script>

<Button
    variant="confirm"
    data-ledger="add"
    aria-expanded={adding}
    aria-controls="ledger-add-panel"
    onclick={onAdd}
>
    <svg class="ledger-add__icon" viewBox="0 0 10 10" aria-hidden="true">
        <path d="M5 1v8M1 5h8" />
    </svg>
    {t(LEDGER_KEYS.editorSummary)}
</Button>

<style>
  @layer components {
    .ledger-add__icon {
        width: 10px;
        height: 10px;
        fill: none;
        stroke: currentColor;
        stroke-width: 1.6;
    }
  }
</style>
