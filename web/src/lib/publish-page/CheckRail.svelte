
<script lang="ts">
    import { buttonAttrs } from '../base/classes';
    import type { Translate } from '../sessions/types';
    import CheckMark from './CheckMark.svelte';
    import type { CheckCell } from './checks-model';
    import { gateLabelKey, resultKey, type GateId } from './report-format';
    import './checks.css';

    interface Props {
        cells: readonly CheckCell[];
        open: (id: GateId) => boolean;
        t: Translate;
        onToggle: (id: GateId) => void;
    }
    const { cells, open, t, onToggle }: Props = $props();
</script>

<div class="d-rail" role="group" aria-label={t('publish.page.checks.aria')} data-pp="CheckRail">
    {#each cells as cell (cell.id)}
        <button type="button" class="d-tick" {...buttonAttrs('row', 'md')} data-result={cell.result} aria-expanded={open(cell.id)} onclick={() => onToggle(cell.id)}>
            <CheckMark result={cell.result} shapeOnly />
            <span class="d-tick__l pp-ident">{t(gateLabelKey(cell.id))}</span>
            <span class="d-sr">{t(resultKey(cell.result))}</span>
        </button>
    {/each}
</div>
