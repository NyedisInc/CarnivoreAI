
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import { SUBMIT_KEYS } from '../../../../client/js/labels/skill-submit.js';
    import type { Translate } from '../sessions/types';
    import type { CatalogFilters } from './filter';
    import { kindChipsFor, stateOf, withState, STATE_SEGMENTS, stateTip } from './filter-groups';
    import type { StateGroup } from './filter-groups';
    import KindMark from './KindMark.svelte';

    interface Props {
        filters: CatalogFilters;
        kinds: readonly string[];
        t: Translate;
        onFilters: (next: CatalogFilters) => void;
        onPublish: () => void;
    }

    const { filters, kinds, t, onFilters, onPublish }: Props = $props();

    const kindChips = $derived(kindChipsFor(kinds, filters.kind, t));
    const state = $derived(stateOf(filters));

    function pickKind(kind: string | null): void {
        onFilters({ ...filters, kind });
    }

    function pickState(next: StateGroup): void {
        onFilters(withState(filters, next));
    }
</script>

<nav class="cat-rail" aria-label={t('skill.filter.legend')}>
    {#if kindChips.length}
        <div class="cat-rail__group" data-group="kind" role="radiogroup" aria-label={t('warez.group.kind')}>
            <span class="cat-rail__label">{t('warez.group.kind')}</span>
            <button type="button" class="cat-rail__row bar__kind" role="radio" aria-checked={filters.kind === null} onclick={() => pickKind(null)}>{t(BROWSE_KEYS.kindChipAll)}</button>
            {#each kindChips as chip (chip.kind)}
                <button type="button" class="cat-rail__row bar__kind" role="radio" aria-checked={filters.kind === chip.kind} data-kind={chip.kind} onclick={() => pickKind(chip.kind)}>
                    <KindMark kind={chip.kind} size="sm" {t} />{chip.label}
                </button>
            {/each}
        </div>
    {/if}
    <div class="cat-rail__group" data-group="state" role="radiogroup" aria-label={t('warez.group.state')}>
        <span class="cat-rail__label">{t('warez.group.state')}</span>
        <button type="button" class="cat-rail__row bar__flag" role="radio" aria-checked={state === 'any'} title={t(BROWSE_KEYS.stateTipAny)} onclick={() => pickState('any')}>{t('warez.filter.any')}</button>
        {#each STATE_SEGMENTS as [value, key] (value)}
            <button type="button" class="cat-rail__row bar__flag" role="radio" aria-checked={state === value} title={stateTip(value, t)} onclick={() => pickState(value)}>{t(key)}</button>
        {/each}
    </div>
    <div class="cat-rail__foot">
        <button type="button" class="modal-btn modal-btn-secondary warez-act" id="catalog-submit-open" onclick={onPublish}>{t(SUBMIT_KEYS.submitAction)}</button>
    </div>
</nav>

<style>
    .cat-rail {
        display: flex;
        flex-direction: column;
        gap: 14px;
        box-sizing: border-box;
        width: 168px;
        min-height: 0;
        overflow-y: auto;
        padding: 12px 0;
        background: var(--oc-ground-panel);
        box-shadow: inset -1px 0 0 0 var(--oc-line-rule);
        font-family: var(--font-mono);
    }

    .cat-rail__group {
        display: flex;
        flex-direction: column;
    }

    .cat-rail__label {
        padding: 0 12px 6px;
        color: var(--oc-text-muted);
        font-size: 10px;
        letter-spacing: 0.6px;
        text-transform: uppercase;
    }

    .cat-rail__row {
        display: flex;
        align-items: center;
        gap: 6px;
        height: var(--oc-rowheight, 26px);
        padding: 0 12px;
        border: 0;
        border-left: 2px solid transparent;
        background: transparent;
        color: var(--oc-text-secondary);
        font: inherit;
        font-size: 11px;
        text-align: left;
        cursor: pointer;
    }

    .cat-rail__row:hover {
        background: var(--oc-ground-hover);
        color: var(--oc-text-primary);
    }

    .cat-rail__row[aria-checked='true'] {
        border-left-color: var(--oc-orange);
        background: var(--oc-orange-tint);
        color: var(--oc-text-bright);
    }

    .cat-rail__foot {
        margin-top: auto;
        padding: 0 12px;
    }

    .cat-rail__foot :global(.modal-btn) {
        width: 100%;
    }
</style>
