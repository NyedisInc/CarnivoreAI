
<script lang="ts">
    import { SKILL_KEYS, reasonOf, refusalMessage } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import type { CatalogHost } from './catalog';
    import { refusalCodeOf } from './install-actions';
    import RatingGlyph from '../rating/RatingGlyph.svelte';
    import { GATE_CANCELLED, guarded, type RegisterGate } from './register-gate.svelte';
    import {
        MAX_RATING_TEXT,
        STAR_VALUES,
        clampText,
        rateBlocked,
        removedOf,
        yourStarsOf,
    } from './rating-write';

    interface Props {
        itemId: string | null;
        host: CatalogHost;
        t: Translate;
        signedIn: boolean;
        installed?: boolean;
        /* could not */
        onWritten?: () => void;
        gate?: RegisterGate;
        initialStars?: number | null;
        initialText?: string | null;
    }

    const { itemId, host, t, signedIn, installed = true, onWritten, gate, initialStars = null, initialText = null }: Props = $props();

    let words = $state('');
    let savedText = $state('');
    let editing = $state(false);
    let working = $state(false);
    let yourStars = $state<number | null>(null);
    let notice = $state<string | null>(null);
    let refusal = $state<string | null>(null);
    let failure = $state<string | null>(null);

    const blocked = $derived(rateBlocked(signedIn, installed));


    $effect(() => {
        void itemId;
        editing = false;
        yourStars = null;
        notice = null;
        refusal = null;
        failure = null;
    });

    $effect(() => {
        yourStars = initialStars;
        savedText = initialText ?? '';
        words = initialText ?? '';
    });

    /* could not be reached */
    function report(error: unknown): void {
        const code = refusalCodeOf(error);
        if (code) refusal = refusalMessage(code, t);
        else failure = t(SKILL_KEYS.ratingWriteFailed, { reason: reasonOf(error, t) });
    }

    function reset(): void {
        notice = null;
        refusal = null;
        failure = null;
    }

    async function save(stars: number, text: string): Promise<void> {
        if (working || blocked !== null || !itemId) return;
        working = true;
        reset();
        try {
            const id = itemId;
            const answer = await guarded(gate, () => host.rateItem(id, { stars, text: clampText(text) }));
            if (answer === GATE_CANCELLED) {
                refusal = t('community.gate.needed');
                return;
            }
            yourStars = yourStarsOf(answer);
            savedText = clampText(text);
            editing = false;
            notice = t(SKILL_KEYS.ratingSaved);
            onWritten?.();
        } catch (error) {
            report(error);
        } finally {
            working = false;
        }
    }

    async function remove(): Promise<void> {
        if (blocked !== null || working || !itemId) return;
        working = true;
        reset();
        try {
            const answer = await host.removeRating(itemId);
            notice = removedOf(answer) === false
                ? t(SKILL_KEYS.ratingNotRemoved)
                : t(SKILL_KEYS.ratingRemoved);
            yourStars = null;
            savedText = '';
            words = '';
            editing = false;
            onWritten?.();
        } catch (error) {
            report(error);
        } finally {
            working = false;
        }
    }
</script>

<div class="rate">
    <div class="rate__row">
        <span class="rate__heading">{t(SKILL_KEYS.ratingMineHeading)}</span>
        
        <div class="rate__stars" role="group" aria-label={t(SKILL_KEYS.ratingMineHeading)}>
            <span class="rate__bracket" aria-hidden="true">[</span>
            {#each STAR_VALUES as value}
                <button
                    type="button"
                    class="rate__star"
                    disabled={blocked !== null || working}
                    aria-pressed={yourStars === value}
                    aria-label={t(SKILL_KEYS.ratingStar, { stars: value })}
                    onclick={() => void save(value, savedText)}
                ><RatingGlyph size={18} fill={yourStars !== null && value <= yourStars ? 1 : 0} /></button>
            {/each}
            <span class="rate__bracket" aria-hidden="true">]</span>
        </div>
        {#if yourStars !== null && blocked === null}
            <button type="button" class="rate__link" disabled={working} onclick={() => { editing = !editing; words = savedText; }}>
                {t(savedText ? SKILL_KEYS.ratingCommentEdit : SKILL_KEYS.ratingCommentAdd)}
            </button>
            <button type="button" class="rate__link" disabled={working} onclick={() => void remove()}>{t(SKILL_KEYS.ratingRemove)}</button>
        {/if}
    </div>
    {#if savedText && !editing}
        <p class="rate__saved">{savedText}</p>
    {/if}
    {#if editing && yourStars !== null}
        <textarea
            class="rate__box"
            rows="2"
            maxlength={MAX_RATING_TEXT}
            aria-label={t(SKILL_KEYS.ratingTextLabel)}
            disabled={blocked !== null || working}
            bind:value={words}
        ></textarea>
        <div class="rate__acts">
            <button type="button" class="modal-btn modal-btn-confirm" disabled={working} onclick={() => void save(yourStars as number, words)}>
                {working ? t(SKILL_KEYS.ratingSubmitWorking) : t(SKILL_KEYS.ratingCommentSave)}
            </button>
            <button type="button" class="modal-btn modal-btn-secondary" disabled={working} onclick={() => { editing = false; }}>{t('community.cancel')}</button>
        </div>
    {/if}
    {#if blocked === 'signed_out'}
        
        <p class="rate__note">{t(SKILL_KEYS.ratingSignedOut)}</p>
    {/if}
    {#if blocked === 'not_installed'}
        <p class="rate__note">{t(SKILL_KEYS.ratingNotInstalled)}</p>
    {/if}
    {#if notice}
        <p class="rate__note" role="status">{notice}</p>
    {/if}
    {#if refusal}
        <p class="rate__note rate__note--out" role="status">{refusal}</p>
    {/if}
    {#if failure}
        <p class="rate__note rate__note--out" role="status">{failure}</p>
    {/if}
</div>

<style>
    .rate {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding-top: 6px;
        border-top: 1px solid var(--cat-line-quiet);
    }

    .rate__row {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 10px;
    }

    .rate__heading {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .rate__stars {
        display: inline-flex;
        align-items: center;
        font-family: var(--font-mono, monospace);
        font-size: 18px;
        line-height: 1;
    }

    .rate__bracket {
        color: var(--rating-off, var(--oc-line-rule));
    }

    .rate__star {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 44px;
        min-height: 44px;
        padding: 3px 1px;
        border: 1px solid transparent;
        border-radius: 2px;
        background: transparent;
        cursor: pointer;
    }

    .rate__star:hover:not(:disabled) {
        border-color: var(--cat-line);
    }

    .rate__link {
        padding: 0;
        border: none;
        background: transparent;
        color: var(--cat-muted);
        font-size: 11px;
        cursor: pointer;
    }

    .rate__link:hover:not(:disabled) {
        color: var(--cat-text);
    }

    .rate__saved {
        margin: 0;
        color: var(--cat-text);
        font-size: 12px;
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    .rate__box {
        width: 100%;
        box-sizing: border-box;
        padding: 6px 8px;
        border: 1px solid var(--cat-line);
        border-radius: 3px;
        background: var(--cat-ground);
        color: var(--cat-text);
        font-family: var(--cat-mono);
        font-size: 12px;
        resize: vertical;
    }

    .rate__acts {
        display: flex;
        gap: 8px;
    }

    .rate :global(.modal-btn) {
        padding: 7px 16px;
        font-size: 13px;
    }

    .rate__star:disabled,
    .rate__link:disabled,
    .rate__box:disabled {
        opacity: 0.55;
        cursor: default;
    }

    .rate__note {
        margin: 0;
        color: var(--cat-muted);
        font-size: 11px;
        line-height: 1.45;
    }

    .rate__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
    }

    @media (max-width: 767px) {
        .rate__star {
            padding: 10px;
        }

        .rate__link {
            min-height: 44px;
        }
    }
</style>
