
<script lang="ts">
    import type { Snippet } from 'svelte';
    import AuthorLink from '../community/AuthorLink.svelte';
    import RatingStars from '../rating/RatingStars.svelte';
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Developer } from './item-feedback';
    import { scrollToRatings } from './item-feedback';
    import type { RatingsReader } from './ratings-reader.svelte';
    import { t } from '../i18n/index.svelte';
    import { isReadonly } from './readonly';

    interface Props {
        itemId: string | null;
        reader: RatingsReader;
        id: string;
        source: string;
        developer: Developer | null;
        version: string | null;
        actions?: Snippet;
        part?: 'all' | 'rating' | 'facts';
        ratingSize?: number;
    }

    const { itemId, reader, id, source, developer, version, actions, part = 'all', ratingSize = 16 }: Props = $props();
    const readonly = isReadonly();
</script>

{#if part !== 'facts'}
<div class="isum">
    {#if itemId && !readonly && reader.view.shape !== 'unavailable'}
        <span class="isum-rating">
            <RatingStars value={reader.view.average ?? 0} size={ratingSize} label={t(SKILL_KEYS.ratingAverage, { average: reader.view.average ?? 0 })} />
            <button type="button" class="isum-rating-link" data-ratings-link onclick={() => scrollToRatings()}>
                {reader.view.shape === 'none' ? t(SKILL_KEYS.ratingNoneShort) : t(SKILL_KEYS.ratingCount, { count: reader.view.count })}
            </button>
        </span>
    {/if}
    {@render actions?.()}
</div>
{/if}

{#if part !== 'rating'}
<dl class="isum-facts">
    <dt>{t('themes.page.fact.id')}</dt><dd>{id}</dd>
    <dt>{t('themes.page.fact.source')}</dt><dd>{source}</dd>
    <dt>{t('themes.page.fact.developer')}</dt>
    <dd>
        {#if developer && developer.kind === 'publisher'}
            {#if developer.profileHandle}
                <AuthorLink {t} handle={developer.profileHandle} />
            {:else}
                {developer.handle}
            {/if}
            {#if developer.githubHref}
                <a href={developer.githubHref} target="_blank" rel="noopener noreferrer">
                    {t('themes.page.developer.github')}
                </a>
            {/if}
        {:else if developer && developer.kind === 'author'}
            {developer.text}
        {:else}
            {t('themes.page.fact.unset')}
        {/if}
    </dd>
    <dt>{t('themes.page.fact.version')}</dt><dd>{version || t('themes.page.fact.unset')}</dd>
</dl>
{/if}

<style>
  @layer components {
    .isum {
        display: flex;
        margin-top: -6px;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 8px;
    }

    .isum-rating {
        display: inline-flex;
        align-items: center;
        gap: 8px;
    }

    .isum-rating-link {
        padding: 0;
        border: none;
        background: transparent;
        color: var(--oc-text-secondary);
        font: inherit;
        font-size: var(--oc-fs-label, 12px);
        text-decoration: underline;
        text-underline-offset: 3px;
        cursor: pointer;
    }

    .isum-rating-link:hover {
        color: var(--oc-text-primary);
    }

    .isum-facts {
        display: grid;
        grid-template-columns: max-content 1fr;
        gap: 4px 14px;
        margin: 0;
        padding: 10px 0;
        border-top: 1px solid var(--oc-line-faint);
        border-bottom: 1px solid var(--oc-line-faint);
        font-size: var(--oc-fs-label, 12px);
    }

    .isum-facts dt {
        letter-spacing: var(--oc-tracking-label, 0.08em);
        text-transform: uppercase;
        color: var(--oc-text-dim);
    }

    .isum-facts dd {
        margin: 0;
        min-width: 0;
        overflow-wrap: anywhere;
        color: var(--oc-text-primary);
    }
  }
</style>
