
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import { kindLabel } from '../../../../client/js/labels/catalog-kind.js';
    import type { Translate } from '../sessions/types';
    import type { CardView } from './card';

    interface Props {
        cards: readonly CardView[];
        selectedId: string | null;
        t: Translate;
        onSelect: (id: string | null) => void;
    }

    const { cards, selectedId, t, onSelect }: Props = $props();

    const packs = $derived(cards.filter((card) => card.isLoadout && card.id));
</script>

{#if packs.length}
    <section class="cat-packs" aria-label={t(BROWSE_KEYS.packsHeading)}>
        <span class="cat-packs__heading">{t(BROWSE_KEYS.packsHeading)}</span>
        <div class="cat-packs__row">
            {#each packs as pack (pack.renderKey)}
                <button
                    type="button"
                    class="cat-packs__card"
                    class:cat-packs__card--on={pack.id === selectedId}
                    aria-pressed={pack.id === selectedId}
                    onclick={() => onSelect(pack.id)}
                >
                    <span class="cat-packs__head">
                        <span class="oc-icon-tile" aria-hidden="true">{Array.from(pack.headline ?? '?')[0]?.toUpperCase()}</span>
                        <span class="cat-packs__name">{pack.headline}</span>
                    </span>
                    {#if pack.brief}<span class="cat-packs__brief">{pack.brief}</span>{/if}
                    <span class="cat-packs__foot">
                        <span class="catalog-mark catalog-mark--quiet">{kindLabel(pack.kind, t) ?? ''}</span>
                        {#if pack.publisher}<span class="cat-packs__by">{t(SKILL_KEYS.cardPublisher, { publisher: pack.publisher })}</span>{/if}
                    </span>
                </button>
            {/each}
        </div>
    </section>
{/if}

<style>
    .cat-packs {
        display: flex;
        flex: none;
        flex-direction: column;
        gap: var(--oc-space-2);
        padding-top: var(--oc-space-3);
    }

    .cat-packs__heading {
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro, 10px);
        letter-spacing: var(--oc-tracking-label, 0.6px);
        text-transform: uppercase;
    }

    .cat-packs__row {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr));
        gap: var(--oc-space-3);
    }

    .cat-packs__card {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        min-width: 0;
        min-height: 104px;
        padding: var(--oc-space-3);
        border: 1px solid var(--oc-line-surface);
        border-radius: var(--oc-radius);
        background: var(--oc-surface-1);
        color: var(--oc-text-primary);
        font-family: inherit;
        text-align: left;
        cursor: pointer;
    }

    .cat-packs__card:hover,
    .cat-packs__card--on {
        background: var(--oc-surface-1-on);
    }

    .cat-packs__head {
        display: flex;
        align-items: center;
        gap: var(--oc-space-3);
        min-width: 0;
    }

    .cat-packs__name {
        min-width: 0;
        font-size: 13px;
        font-weight: 600;
        overflow-wrap: anywhere;
    }

    .cat-packs__brief {
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 3;
        line-clamp: 3;
        overflow: hidden;
        color: var(--oc-text-secondary);
        font-size: 12px;
        line-height: 1.4;
    }

    .cat-packs__foot {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--oc-space-2);
        margin-top: auto;
    }

    .cat-packs__by {
        min-width: 0;
        overflow: hidden;
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro, 10px);
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .catalog-mark {
        padding: 1px 6px;
        border: 1px solid var(--oc-line-surface);
        border-radius: var(--oc-control-radius, 2px);
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro, 10px);
    }

    @media (max-width: 767px) {
        .cat-packs__row {
            grid-template-columns: none;
            grid-auto-flow: column;
            grid-auto-columns: min(78%, 280px);
            overflow-x: auto;
            scroll-snap-type: x proximity;
            scrollbar-width: none;
        }

        .cat-packs__card {
            scroll-snap-align: start;
        }
    }
</style>
