<!-- could not -->
<script lang="ts">
    import {
        SKILL_KEYS,
        reviewKindLabel,
        reviewLabel,
        reviewVerdictLabel,
    } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import { reviewView } from './review';
    import type { CatalogReview } from './types';

    interface Props {
        review?: CatalogReview | null;
        t: Translate;
        part?: 'full' | 'main' | 'tail';
        grade?: string | null;
    }

    const { review = null, t, part = 'full', grade = null }: Props = $props();

    const subLine = $derived.by(() => {
        const raw = (review ?? {}) as { model?: unknown; reviewed_at?: unknown };
        const model = typeof raw.model === 'string' ? raw.model.split('/').pop() : null;
        const date = typeof raw.reviewed_at === 'string' ? raw.reviewed_at.slice(0, 10) : null;
        return [status, grade ? t('warez.trust.grade', { grade }) : null, model, date].filter(Boolean).join(' \u00b7 ');
    });

    const view = $derived(reviewView(review));

    const status = $derived(view.shape === 'absent' ? null : reviewLabel(view.shape, t));

    const verdict = $derived(reviewVerdictLabel(view.verdict, t));
</script>

{#if part === 'tail'}
    <section class="cat-review cat-review--tail">
        {#if view.shape === 'reviewed' && !view.warnings.length && !view.malformed}
            <p class="cat-review__note">{t(SKILL_KEYS.reviewNoWarnings)}</p>
        {/if}
        <p class="cat-review__advisory">{t(SKILL_KEYS.reviewAdvisory)}</p>
    </section>
{:else}
<section class="cat-review" aria-label={t(SKILL_KEYS.reviewHeading)}>
    <div class="cat-review__head">
        <span class="cat-review__heading">{t(SKILL_KEYS.reviewHeading)}</span>
        
        {#if status && part === 'full'}
            <span
                class="cat-review__status"
                class:cat-review__status--out={view.shape === 'unavailable'}
            >{status}</span>
        {/if}
        <!-- could not -->
        
        {#if verdict && !view.overridden && (part === 'full' || view.verdict !== 'clean')}
            <span
                class="cat-review__status"
                class:cat-review__status--out={view.verdict !== 'clean'}
            >{verdict}</span>
        {/if}
    </div>

    {#if part === 'main' && status}
        <div class="cat-review__sub">{subLine}</div>
    {/if}
    {#if view.shape === 'absent'}
        <p class="cat-review__note">{t(SKILL_KEYS.reviewAbsent)}</p>
    {:else if view.shape === 'unavailable'}
        
        <p class="cat-review__note cat-review__note--out" role="status">
            {t(SKILL_KEYS.reviewUnavailableDetail)}
        </p>
    {:else}
        {#if view.verdict === null}
            
            <p class="cat-review__note cat-review__note--out" role="status">
                {t(SKILL_KEYS.reviewVerdictAbsent)}
            </p>
        {:else if view.verdict === 'unreadable'}
            
            <p class="cat-review__note cat-review__note--out" role="status">
                {t(SKILL_KEYS.reviewVerdictUnreadableDetail)}
            </p>
        {/if}

        {#if view.summary}
            <p class="cat-review__summary">{view.summary}</p>
        {:else}
            <p class="cat-review__note">{t(SKILL_KEYS.reviewSummaryAbsent)}</p>
        {/if}

        {#if view.warnings.length}
            <ul class="cat-review__warnings">
                {#each view.warnings as warning}
                    <li class="cat-review__warning">
                        <span class="cat-review__kind">{reviewKindLabel(warning.kind, t)}</span>
                        {#if warning.detail}
                            <span class="cat-review__detail">
                                {warning.detail}
                                
                                {#if warning.file}
                                    <span class="cat-review__where">
                                        {warning.line === null
                                            ? t(SKILL_KEYS.reviewWarningWhere, { file: warning.file })
                                            : t(SKILL_KEYS.reviewWarningWhereLine, {
                                                  file: warning.file,
                                                  line: warning.line,
                                              })}
                                    </span>
                                {/if}
                            </span>
                        {:else}
                            
                            <span class="cat-review__detail cat-review__detail--quiet">
                                {t(SKILL_KEYS.reviewWarningNoDetail)}
                            </span>
                        {/if}
                    </li>
                {/each}
            </ul>
        {:else if part === 'full'}
            
            <p class="cat-review__note">{t(SKILL_KEYS.reviewNoWarnings)}</p>
        {/if}

        {#if view.malformed}
            <!-- could not -->
            <p class="cat-review__note cat-review__note--out" role="status">
                {t(SKILL_KEYS.reviewWarningsMalformed)}
            </p>
        {/if}
    {/if}

    {#if part === 'full'}
        <p class="cat-review__advisory">{t(SKILL_KEYS.reviewAdvisory)}</p>
    {/if}
</section>
{/if}

<style>
    .cat-review {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 10px 12px;
        border: 1px solid var(--cat-line);
        border-radius: 4px;
        background: var(--cat-panel);
    }

    .cat-review__head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 10px;
    }

    .cat-review__heading {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-review__status {
        flex-shrink: 0;
        padding: 1px 6px;
        border: 1px solid var(--cat-line);
        border-radius: 3px;
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-review__status--out {
        border-color: var(--cat-attention);
        color: var(--cat-attention);
    }

    .cat-review__sub {
        color: var(--oc-text-muted);
        font-size: 11px;
        overflow-wrap: anywhere;
    }
    .cat-review__summary {
        margin: 0;
        color: var(--cat-text);
        font-size: 12px;
        line-height: 1.5;
        overflow-wrap: anywhere;
    }

    .cat-review__note {
        margin: 0;
        color: var(--cat-muted);
        font-size: 12px;
        line-height: 1.45;
    }

    .cat-review__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
    }

    .cat-review__warnings {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .cat-review__warning {
        display: flex;
        gap: 10px;
        align-items: baseline;
        padding: 4px 0;
        border-top: 1px solid var(--cat-line-quiet);
    }

    .cat-review__warning:first-child {
        border-top: none;
    }

    .cat-review__kind {
        flex-shrink: 0;
        min-width: 11ch;
        color: var(--cat-attention);
        font-family: var(--cat-mono);
        font-size: 11px;
        overflow-wrap: anywhere;
    }

    .cat-review__detail {
        color: var(--cat-text);
        font-size: 12px;
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    .cat-review__detail--quiet {
        color: var(--cat-muted);
    }

    .cat-review__where {
        display: inline-block;
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 11px;
        overflow-wrap: anywhere;
    }

    .cat-review__advisory {
        margin: 2px 0 0;
        color: var(--cat-faint);
        font-size: 11px;
        line-height: 1.4;
    }

    @media (max-width: 767px) {
        .cat-review__warning {
            flex-direction: column;
            gap: 2px;
        }

        .cat-review__kind {
            min-width: 0;
        }
    }
</style>
