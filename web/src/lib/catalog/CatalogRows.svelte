<!-- its own sentence -->
<script lang="ts">
    import { motionReduced } from '../motion/motion';
    import type { Snippet } from 'svelte';
    import { flip } from 'svelte/animate';
    import { fade } from 'svelte/transition';
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import CatalogCard from './CatalogCard.svelte';
    import './warez-card.css';
    import type { AddProject } from './add-projects';
    import PacksShelf from './PacksShelf.svelte';
    import type { ManagerView } from '../manager-frame/view-memory';
    import type { CardView } from './card';
    import { NO_PALETTES, type CatalogData } from './catalog-data.svelte';
    import type { PreviewPalette } from '../themes-page/preview-palette';
    import { IDLE } from './install-actions';
    import { kindsOf } from './filter';

    interface Props {
        data: CatalogData;
        shown: readonly CardView[];
        shownUntrusted: readonly CardView[];
        narrowed: boolean;
        selectedId: string | null;
        t: Translate;
        view: ManagerView;
        onSelect: (id: string | null) => void;
        onSheet: (card: CardView) => void;
        onClearFilters: () => void;
        projects?: readonly AddProject[];
        onAdd?: ((card: CardView, target: 'global' | 'project', projectPath?: string) => void) | null;
        kind?: string | null;
        highlights?: Snippet;
        shelf?: boolean;
        palettes?: ReadonlyMap<string, PreviewPalette>;
        status?: Snippet;
        onSignIn?: () => void;
    }

    const {
        data,
        shown,
        shownUntrusted,
        narrowed,
        selectedId,
        t,
        view,
        onSelect,
        onSheet,
        onClearFilters,
        projects = [],
        onAdd = null,
        highlights,
        kind = null,
        shelf = true,
        palettes = NO_PALETTES,
        status,
        onSignIn,
    }: Props = $props();

    const total = $derived(data.cards.length + data.untrustedCards.length);
    const packCount = $derived(shelf ? data.cards.filter((card) => card.isLoadout && card.id).length : 0);
    const visible = $derived(shown.length + shownUntrusted.length + packCount);
    const kindAbsent = $derived(!!kind && !kindsOf([...data.cards, ...data.untrustedCards]).includes(kind));

    const CAN_ANIMATE =
        typeof window !== 'undefined' &&
        typeof Element !== 'undefined' &&
        typeof Element.prototype.animate === 'function' &&
        typeof Element.prototype.getAnimations === 'function' &&
        !motionReduced();
    const motion = $derived(CAN_ANIMATE && view === 'grid' ? 180 : 0);
    const SKELETONS = Array.from({ length: 12 }, (_, i) => i);
</script>

{#snippet item(card: CardView, trusted: boolean)}
    {#if trusted}
        <CatalogCard
            list={view === 'list'}
            selected={card.id === selectedId}
            {card}
            {t}
            palette={card.id ? (palettes.get(card.id) ?? null) : null}
            state={data.stateFor(card.id)}
            onInstall={() => onSheet(card)}
            onUpdate={() => onSheet(card)}
            onOpen={() => onSelect(card.id)}
            rows={card.id ? (data.installed[card.id] ?? []) : []}
            {projects}
            onAdd={onAdd ? (target, projectPath) => onAdd(card, target, projectPath) : null}
        />
    {:else}
        
        <CatalogCard
            list={view === 'list'}
            selected={card.id === selectedId}
            {card}
            {t}
            state={IDLE}
            onInstall={() => {}}
            onUpdate={() => {}}
            onOpen={() => onSelect(card.id)}
        />
    {/if}
{/snippet}

<div class="rows">
    {#if highlights}{@render highlights()}{/if}
    {#if shelf}<PacksShelf cards={data.cards} {selectedId} {t} {onSelect} />{/if}

    <div class="rows__head">
        <span>{t('warez.head.all')}</span>
        <span>{data.loading ? '-' : t('warez.head.count', { shown: visible, total })}</span>
        {#if status}<div class="rows__hstat">{@render status()}</div>{/if}
    </div>

    {#if data.loading}
        <div class="rows__list rows__list--grid warez-grid" aria-busy="true">
            <span class="rows__sr" role="status">{t(SKILL_KEYS.catalogLoading)}</span>
            {#each SKELETONS as n (n)}<div class="rows__skel"></div>{/each}
        </div>
    {:else if data.failure}
        
        <div class="rows__empty rows__empty--failed" role="status">
            <p>{t(SKILL_KEYS.catalogUnavailable, { reason: data.failure })}</p>
        </div>
    {:else if data.isEmpty}
        <div class="rows__empty"><p>{t(SKILL_KEYS.catalogEmpty)}</p></div>
    {:else if visible === 0}
        
        <div class="rows__empty" role="status">
            <p>{kindAbsent ? t(kind === 'mod' ? 'warez.empty.mods' : 'warez.empty.kind') : t('skills.hub.hl.none')}</p>
            <span>{kindAbsent ? t('warez.empty.kind_detail') : t('warez.empty.nomatch_detail')}</span>
            <button type="button" class="oc-btn rows__clear" onclick={onClearFilters}>
                {t(SKILL_KEYS.screenClearFilters)}
            </button>
        </div>
    {/if}

    {#if shown.length}
        <div class="rows__list" class:rows__list--grid={view === 'grid'} class:warez-grid={view === 'grid'}>
            {#if motion}
                {#each shown as card (card.renderKey)}
                    <div class="rows__row" animate:flip={{ duration: motion }} in:fade={{ duration: motion }}>{@render item(card, true)}</div>
                {/each}
            {:else}
                {#each shown as card (card.renderKey)}
                    <div class="rows__row">{@render item(card, true)}</div>
                {/each}
            {/if}
        </div>
    {/if}

    {#if shownUntrusted.length}
        <div class="rows__untrusted">
            <p class="rows__untrusted-heading">{t(SKILL_KEYS.catalogUntrustedHeading)}</p>
            <p class="rows__note">{t(SKILL_KEYS.catalogUntrustedNote)}</p>
            <div class="rows__list" class:rows__list--grid={view === 'grid'} class:warez-grid={view === 'grid'}>
                {#if motion}
                    {#each shownUntrusted as card (card.renderKey)}
                        <div class="rows__row" animate:flip={{ duration: motion }} in:fade={{ duration: motion }}>{@render item(card, false)}</div>
                    {/each}
                {:else}
                    {#each shownUntrusted as card (card.renderKey)}
                        <div class="rows__row">{@render item(card, false)}</div>
                    {/each}
                {/if}
            </div>
        </div>
    {/if}

    {#if onSignIn}
        <button type="button" class="rows__signin" data-catalog-signin-cta onclick={onSignIn}>{t('skills.hub.signin')}</button>
    {/if}
</div>

<style>
    .rows {
        display: flex;
        flex-direction: column;
        container-type: inline-size;
        --rows-gutter: max(var(--oc-page-gutter, 16px), calc((100cqw - 1680px) / 2 + var(--oc-page-gutter, 16px)));
        overflow: auto;
        min-height: 0;
    }

    .rows > * {
        padding-inline: var(--rows-gutter);
    }

    .rows__head {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 4px 12px;
        padding-top: 12px;
        color: var(--oc-text-muted);
        font-size: 10px;
        letter-spacing: 0.6px;
        text-transform: uppercase;
    }

    .rows__signin {
        align-self: flex-start;
        padding-block: 8px 16px;
        border: 0;
        background: none;
        color: var(--oc-text-secondary);
        font: inherit;
        font-size: 11px;
        text-decoration: underline;
        cursor: pointer;
    }

    .rows__signin:hover {
        color: var(--oc-text-primary);
    }

    .rows__hstat {
        display: none;
        flex: 1 1 100%;
        font-size: 11px;
        letter-spacing: 0;
        line-height: 1.4;
        text-transform: none;
    }

    .rows__list {
        display: flex;
        flex-direction: column;
    }

    .rows__list--grid {
        display: grid;
        padding-block: 12px 24px;
        min-width: 0;
    }

    .rows__list:not(.rows__list--grid) {
        padding-block: 8px 24px;
    }

    .rows__row {
        min-width: 0;
    }

    .rows__list--grid .rows__row {
        display: flex;
    }

    .rows__list--grid .rows__row > :global(.catalog-card) {
        flex: 1 1 auto;
    }

    .rows__skel {
        height: 224px;
        border: 1px solid var(--oc-line-faint);
        border-radius: 4px;
    }

    .rows__sr {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip-path: inset(50%);
    }

    .rows__empty {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 12px;
        padding-block: 48px;
        color: var(--oc-text-muted);
        font-size: 12px;
        line-height: 1.45;
    }

    .rows__empty p {
        margin: 0;
        color: var(--oc-text-secondary);
    }

    .rows__empty--failed {
        margin: 12px var(--rows-gutter) 0;
        padding: 12px;
        border-left: 2px solid var(--oc-coral);
        background: var(--oc-ground-raised);
    }

    .rows__untrusted {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1);
        padding-top: var(--oc-space-2);
        border-top: 1px solid var(--cat-line-quiet);
    }

    .rows__untrusted-heading {
        margin: 0;
        padding: 0;
        color: var(--cat-attention);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .rows__untrusted > .rows__note {
        padding-inline: 0;
    }

    .rows__note {
        margin: 0;
        padding: var(--oc-space-2) 0;
        color: var(--cat-muted);
        font-size: 12px;
        line-height: 1.45;
    }

    .rows__clear {
        margin: 0;
    }

    @media (max-width: 767px) {
        .rows {
            --rows-gutter: 12px;
        }

        .rows__list--grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
            padding-block: 12px;
        }

        .rows__hstat {
            display: block;
        }

        .rows__signin {
            min-height: 44px;
            min-width: 44px;
        }

        .rows__clear {
            min-height: 44px;
        }
    }
</style>
