
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { Translate } from '../sessions/types';
    import VerdictMark from './VerdictMark.svelte';
    import { gradeView } from './grade';
    import { trustView } from './trust';
    import type { CatalogVersion } from './types';

    interface Props {
        version: CatalogVersion | null;
        t: Translate;
        untrusted?: boolean;
    }

    const { version, t, untrusted = false }: Props = $props();

    const view = $derived(trustView(version));
    const grade = $derived(gradeView(version?.grade ?? null));
    const review = $derived((version?.review ?? null) as Record<string, unknown> | null);

    function text(value: unknown, max: number): string | null {
        return typeof value === 'string' && value.trim() ? value.trim().slice(0, max) : null;
    }

    const model = $derived(text(review?.model, 80)?.split('/').pop() ?? null);
    const date = $derived(text(review?.reviewed_at, 10));
    const warnings = $derived(Array.isArray(review?.warnings) ? (review!.warnings as unknown[]).length : 0);
    const reviewed = $derived(view.reviewShape === 'reviewed');
    const verdict = $derived<'clean' | 'flagged' | 'blocked' | 'unreadable'>(
        untrusted ? 'blocked' : (view.verdict ?? 'unreadable'),
    );
    const verdictWord = $derived(untrusted ? t('warez.verdict.untrusted') : t(`warez.verdict.${verdict}`));
    const reviewParts = $derived(
        reviewed
            ? [
                  t('warez.trust.review_line', {
                      model: model ?? '',
                      date: date ?? '',
                      warnings: t('warez.trust.warnings_n', { count: warnings }),
                  }),
              ]
            : [t(BROWSE_KEYS.trustNoReview)],
    );
    const reviewTokens = $derived(reviewParts.flatMap((part) => part.split(' \u00b7 ')));

    const fullDigest = $derived(typeof version?.digest === 'string' ? version.digest : null);
    const fullCommit = $derived(
        typeof (version?.src as { commit?: unknown } | undefined)?.commit === 'string'
            ? ((version!.src as { commit: string }).commit)
            : null,
    );
    const kb = $derived(typeof version?.size === 'number' && version.size > 0 ? Math.max(1, Math.round(version.size / 1024)) : null);
    const files = $derived(typeof version?.files === 'number' ? version.files : null);

    let copied = $state<string | null>(null);
    let failed = $state<string | null>(null);

    async function copy(which: string, value: string | null): Promise<void> {
        if (!value) return;
        try {
            await navigator.clipboard.writeText(value);
            copied = which;
            failed = null;
            setTimeout(() => { if (copied === which) copied = null; }, 1200);
        } catch {
            failed = which;
            copied = null;
        }
    }
</script>

<section class="trust" aria-label={t(BROWSE_KEYS.trustHeading)} data-trust-plate>
    <h3 class="trust__label">{t(BROWSE_KEYS.trustHeading)}</h3>
    <div class="tv-plate" data-verdict={verdict}>
        <div class="tv-pw">
            <span class="tv-word">{verdictWord}</span>
            <span class="tv-psub">{#each reviewTokens as token, k (k)}<span class="tv-nb">{token}{k < reviewTokens.length - 1 ? ' \u00b7' : ''}</span>{' '}{/each}</span>
        </div>
        <VerdictMark {verdict} {t} shapeOnly />
        {#if grade.shape === 'graded' && grade.letter}
            <span class="tv-grade"><b>{grade.letter}</b><i>{t('warez.trust.grade_label')}</i></span>
        {/if}
    </div>
    {#if view.overridden && view.overrideReason}
        <p class="trust__override">{t(BROWSE_KEYS.trustOverride, { reason: view.overrideReason })}</p>
    {/if}
    <div class="tv-grid">
        <div class="tv-cell">
            <div class="tv-kr"><span class="tv-k">{t('warez.trust.signed_by')}</span></div>
            <span class="tv-v">
                {view.signerKey ? t('warez.trust.key', { key: view.signerKey }) : t(BROWSE_KEYS.trustSignerAbsent)}
                <em>{untrusted ? t('warez.trust.not_pinned') : t('warez.trust.pinned')}</em>
            </span>
        </div>
        <div class="tv-cell">
            <div class="tv-kr"><span class="tv-k">{t('warez.trust.scripts_label')}</span></div>
            <span class="tv-v">
                {#if view.scripts === null}
                    {t(BROWSE_KEYS.trustNoReview)}
                {:else if view.scripts > 0}
                    {t('warez.trust.scripts_n', { count: view.scripts })}
                {:else}
                    {t('warez.trust.scripts_none')}
                {/if}
                {#if files !== null && kb !== null}<em>{t('warez.trust.files_kb', { files, kb })}</em>{/if}
            </span>
        </div>
        {#if view.digest}
            <div class="tv-cell">
                <div class="tv-kr">
                    <span class="tv-k">{t('warez.trust.digest')}</span>
                    <button type="button" class="modal-btn modal-btn-secondary tv-copy" onclick={() => void copy('digest', fullDigest)}>
                        {copied === 'digest' ? t('warez.trust.copied') : failed === 'digest' ? t('warez.trust.select_it') : t('warez.trust.copy')}
                    </button>
                </div>
                <span class="tv-v"><code>{view.digest}</code></span>
            </div>
        {/if}
        {#if view.sourceRepo && view.sourceCommit}
            <div class="tv-cell">
                <div class="tv-kr">
                    <span class="tv-k">{t('warez.trust.source_label')}</span>
                    <button type="button" class="modal-btn modal-btn-secondary tv-copy" onclick={() => void copy('commit', fullCommit)}>
                        {copied === 'commit' ? t('warez.trust.copied') : failed === 'commit' ? t('warez.trust.select_it') : t('warez.trust.copy')}
                    </button>
                </div>
                <span class="tv-v">
                    <span class="tv-nb">{view.sourceRepo}</span>
                    <em>{t('warez.trust.source_at', { sha: view.sourceCommit })}</em>
                </span>
            </div>
        {/if}
    </div>
</section>

<style>
    .trust {
        display: flex;
        flex-direction: column;
        gap: 8px;
        min-width: 0;
        font-size: 12px;
    }

    .trust__label {
        display: flex;
        align-items: center;
        margin: 0;
        color: var(--oc-orange);
        font-size: 10px;
        font-weight: 400;
        letter-spacing: 0.8px;
        text-transform: uppercase;
    }

    .trust__override {
        margin: 0;
        color: var(--oc-yellow);
        font-size: 11px;
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    .tv-plate {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px;
        border: 1px solid var(--oc-line-panel);
        border-radius: 2px;
        background: var(--oc-ground-titlerow);
        min-width: 0;
    }

    .tv-plate :global(.verdict-mark) {
        order: -1;
        flex: none;
    }

    .tv-plate :global(.verdict-mark svg) {
        width: 26px;
        height: 26px;
    }

    .tv-pw {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
        flex: 1 1 auto;
    }

    .tv-word {
        font-size: var(--oc-fs-figure, 20px);
        line-height: 1.1;
        color: var(--oc-text-bright);
    }

    .tv-plate[data-verdict='blocked'] .tv-word {
        color: var(--oc-coral);
    }

    .tv-nb {
        white-space: nowrap;
    }

    .tv-plate[data-verdict='clean'] :global(.verdict-mark),
    .tv-plate[data-verdict='unreadable'] :global(.verdict-mark) {
        color: var(--oc-text-primary);
    }

    .tv-psub {
        line-height: 1.4;
        color: var(--oc-text-muted);
        font-size: 11px;
    }

    .tv-grade {
        flex: none;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 2px;
        min-width: 44px;
        padding: 4px 8px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 2px;
    }

    .tv-grade b {
        font-weight: 400;
        font-size: var(--oc-fs-figure, 20px);
        line-height: 1;
        color: var(--oc-text-bright);
    }

    .tv-grade i {
        font-style: normal;
        color: var(--oc-text-muted);
        font-size: 10px;
        letter-spacing: 0.6px;
        text-transform: uppercase;
    }

    .tv-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        border: 1px solid var(--oc-line-panel);
        border-radius: 2px;
    }

    .tv-cell {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        padding: 8px 10px;
        min-width: 0;
        overflow-wrap: anywhere;
        box-shadow: inset -1px -1px 0 0 var(--oc-line-faint);
    }

    .tv-cell:nth-child(2n) {
        box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
    }

    .tv-cell:nth-child(n + 3) {
        grid-column: 1 / -1;
        box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
    }

    .tv-cell:last-child {
        box-shadow: none;
    }

    .tv-kr {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        align-self: stretch;
        min-height: 20px;
    }

    .tv-k {
        color: var(--oc-text-muted);
        font-size: 10px;
        letter-spacing: 0.6px;
        text-transform: uppercase;
    }

    .tv-v {
        color: var(--oc-text-primary);
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 1px;
    }

    .tv-v em {
        font-style: normal;
        color: var(--oc-text-muted);
        font-size: 11px;
    }

    .tv-v code {
        font: inherit;
        color: var(--oc-text-primary);
    }

    .tv-nb {
        white-space: nowrap;
    }

    .tv-copy {
        flex: none;
        margin: -2px 0;
        padding: 2px 8px;
        font-size: 10px;
    }

    @media (max-width: 767px) {
        .tv-grid {
            grid-template-columns: minmax(0, 1fr);
        }

        .tv-cell,
        .tv-cell:nth-child(2n),
        .tv-cell:nth-child(n + 3) {
            grid-column: auto;
            box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
        }

        .tv-cell:last-child {
            box-shadow: none;
        }

        .tv-copy {
            min-height: 44px;
            margin: 0;
            padding: 0 12px;
        }
    }
</style>
