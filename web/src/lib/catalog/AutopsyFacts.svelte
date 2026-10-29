
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { Translate } from '../sessions/types';
    import type { CatalogHost } from './catalog';
    import type { SkillAutopsy } from './types';

    interface Props {
        skill: string;
        host: Pick<CatalogHost, 'skillAutopsy'>;
        t: Translate;
    }

    const { skill, host, t }: Props = $props();

    let autopsy = $state<SkillAutopsy | null>(null);
    let settled = $state(false);

    $effect(() => {
        const name = skill;
        autopsy = null;
        settled = false;
        let cancelled = false;
        void (async () => {
            try {
                const answer = host.skillAutopsy ? await host.skillAutopsy(name) : null;
                if (!cancelled) autopsy = answer;
            } catch (error) {
                console.error('CloudeWeb: the skill autopsy read failed', error);
            } finally {
                if (!cancelled) settled = true;
            }
        })();
        return () => {
            cancelled = true;
        };
    });

    const measured = $derived(autopsy !== null && autopsy.state === 'measured' && typeof autopsy.spans_measured === 'number');
    const recent = $derived(autopsy?.recent ?? []);
    const judged = $derived(autopsy !== null && Array.isArray(autopsy.undisclosed));
    const undisclosed = $derived(autopsy?.undisclosed ?? []);
    const observed = $derived(Object.keys(autopsy?.categories ?? {}));
</script>

{#if settled}
    <section class="cat-autopsy" aria-label={t(BROWSE_KEYS.autopsyHeading)}>
        <span class="cat-autopsy__heading">{t(BROWSE_KEYS.autopsyHeading)}</span>
        {#if measured && autopsy}
            <p class="cat-autopsy__fact">
                {t(BROWSE_KEYS.autopsySummary, {
                    spans: autopsy.spans_measured ?? 0,
                    calls: autopsy.tool_calls ?? 0,
                    errors: autopsy.tool_errors ?? 0,
                    interrupts: autopsy.interrupts ?? 0,
                    corrections: autopsy.corrections ?? 0,
                    measured: autopsy.corrections_measured ?? 0,
                })}
            </p>
            <p class="cat-autopsy__fact">
                {typeof autopsy.tokens_total === 'number'
                    ? t(BROWSE_KEYS.autopsyTokens, { count: autopsy.tokens_total })
                    : t(BROWSE_KEYS.autopsyTokensNone)}
            </p>
            {#if observed.length}
                <p class="cat-autopsy__fact">
                    {t(BROWSE_KEYS.autopsyObserved, { categories: observed.map((c) => c.replace(/_/g, ' ')).join(', ') })}
                </p>
            {/if}
            {#if !judged}
                <p class="cat-autopsy__fact cat-autopsy__fact--muted" data-autopsy="not-judged">
                    {t(BROWSE_KEYS.autopsyNotJudged)}
                </p>
            {:else if undisclosed.length}
                <p class="cat-autopsy__fact cat-autopsy__fact--bad" role="status">
                    {t(BROWSE_KEYS.autopsyUndisclosed, { categories: undisclosed.map((c) => c.replace(/_/g, ' ')).join(', ') })}
                </p>
            {:else}
                <p class="cat-autopsy__fact" data-autopsy="all-disclosed">{t(BROWSE_KEYS.autopsyAllDisclosed)}</p>
            {/if}
            <p class="cat-autopsy__fact cat-autopsy__fact--muted">{t(BROWSE_KEYS.autopsyCoverage)}</p>
            {#if recent.length}
                <span class="cat-autopsy__heading">{t(BROWSE_KEYS.autopsyRecent)}</span>
                <ul class="cat-autopsy__list">
                    {#each recent as span, index (index)}
                        <li class="cat-autopsy__span">
                            {t(BROWSE_KEYS.autopsySpan, {
                                at: (span.fired_at ?? '').slice(0, 16).replace('T', ' '),
                                calls: span.tool_calls,
                                errors: span.tool_errors,
                            })}
                            {#if span.correction && span.next_excerpt}
                                <span class="cat-autopsy__excerpt">{t(BROWSE_KEYS.autopsyCorrection, { excerpt: span.next_excerpt })}</span>
                            {/if}
                        </li>
                    {/each}
                </ul>
            {/if}
        {:else}
            <p class="cat-autopsy__fact">{t(BROWSE_KEYS.autopsyNotMeasured)}</p>
        {/if}
    </section>
{/if}

<style>
    .cat-autopsy {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .cat-autopsy__heading {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-autopsy__fact,
    .cat-autopsy__span {
        margin: 0;
        color: var(--cat-text);
        font-family: var(--cat-mono);
        font-size: 11px;
    }

    .cat-autopsy__fact--muted {
        color: var(--cat-muted);
    }

    .cat-autopsy__fact--bad {
        color: var(--cat-failure);
    }

    .cat-autopsy__list {
        margin: 0;
        padding: 0;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .cat-autopsy__excerpt {
        display: block;
        color: var(--cat-muted);
        overflow-wrap: anywhere;
    }
</style>
