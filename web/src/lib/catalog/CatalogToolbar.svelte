
<script lang="ts">
    import './catalog-phone-bar.css';
    import type { Translate } from '../sessions/types';
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { CatalogFilters } from './filter';
    import { stateOf, withState, pressOrClear, kindChipsFor, STATE_SEGMENTS, stateTip, type StateGroup } from './filter-groups';
    import FilterGroup from './FilterGroup.svelte';
    import KindMark from './KindMark.svelte';

    interface Props {
        filters: CatalogFilters;
        kinds: readonly string[];
        t: Translate;
        onFilters: (next: CatalogFilters) => void;
    }

    const { filters, kinds, t, onFilters }: Props = $props();

    const kindChips = $derived(kindChipsFor(kinds, filters.kind, t));
    const STATES = STATE_SEGMENTS;
    const tip = (value: string): string => stateTip(value, t);

    const state = $derived(stateOf(filters));

    function pickKind(kind: string | null): void {
        onFilters({ ...filters, kind });
    }

    function pickState(next: StateGroup): void {
        onFilters(withState(filters, pressOrClear(state, next as Exclude<StateGroup, 'any'>)));
    }

</script>

{#snippet kindGroup()}
    {#if kindChips.length}
        <FilterGroup id="kind" label={t('warez.group.kind')}>
            <div class="oc-seg" role="radiogroup" aria-label={t('warez.group.kind')}>
                <button type="button" class="oc-seg__item bar__kind" role="radio" aria-checked={filters.kind === null} onclick={() => pickKind(null)}>{t(BROWSE_KEYS.kindChipAll)}</button>
                {#each kindChips as chip (chip.kind)}
                    <button type="button" class="oc-seg__item bar__kind" role="radio" aria-checked={filters.kind === chip.kind} data-kind={chip.kind} onclick={() => pickKind(chip.kind)}>
                        <KindMark kind={chip.kind} size="sm" {t} />{chip.label}
                    </button>
                {/each}
            </div>
        </FilterGroup>
    {/if}
{/snippet}

{#snippet segGroup(id: string, label: string, items: readonly (readonly [string, string])[], current: string, pick: (next: never) => void, withAny: boolean)}
    <FilterGroup {id} {label}>
        <div class="oc-seg" role="radiogroup" aria-label={label}>
            {#if withAny}
                <button type="button" class="oc-seg__item bar__flag" role="radio" aria-checked={current === 'any'} title={t(BROWSE_KEYS.stateTipAny)} onclick={() => pick('any' as never)}>{t('warez.filter.any')}</button>
            {/if}
            {#each items as [value, key] (value)}
                <button
                    type="button"
                    class="oc-seg__item bar__flag"
                    role="radio"
                    aria-checked={current === value}
                    title={tip(value)}
                    onclick={() => pick(value as never)}
                >{t(key)}</button>
            {/each}
        </div>
    </FilterGroup>
{/snippet}

<div class="cat-rows">
    {@render kindGroup()}
    {@render segGroup('state', t('warez.group.state'), STATES, state, pickState, false)}
</div>

<style>
    .cat-rows {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        min-width: 0;
        padding: 4px 12px;
    }

    .bar__flag,
    .bar__kind {
        flex: none;
        height: 100%;
    }

    @media (max-width: 767px) {
        :global(.cat .oc-titlebar__back:not(.wik *)) {
            width: 44px;
            height: 44px;
            margin: 0 -4px 0 -16px;
        }

        :global(.cat .oc-titlebar__omni-row > svg:not(.wik *)) {
            visibility: hidden;
        }

        :global(.cat .oc-titlebar__omni-row .oc-field:not(.wik *)) {
            height: 44px;
            margin-block: -14px;
        }

        .bar__flag,
        .bar__kind {
            min-height: 44px;
        }
    }
</style>
