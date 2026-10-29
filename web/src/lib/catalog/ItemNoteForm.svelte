
<script lang="ts">
    import { MAX_NOTE_CHARS, reasonOfNoteFailure, sendNote } from './item-feedback';
    import { openCatalogScreen } from './screen-host';
    import { t } from '../i18n/index.svelte';

    interface Props {
        itemId: string;
        signedIn: boolean;
    }

    const { itemId, signedIn }: Props = $props();

    let words = $state('');
    let sending = $state(false);
    let sent = $state(false);
    let failure = $state<string | null>(null);

    $effect(() => {
        void itemId;
        words = '';
        sending = false;
        sent = false;
        failure = null;
    });

    const submittable = $derived(
        signedIn && !sending && words.trim().length > 0 && words.length <= MAX_NOTE_CHARS,
    );

    async function submit(): Promise<void> {
        if (!submittable) return;
        sending = true;
        sent = false;
        failure = null;
        try {
            await sendNote(itemId, words);
            words = '';
            sent = true;
        } catch (error) {
            failure = reasonOfNoteFailure(error, t);
        } finally {
            sending = false;
        }
    }
</script>

<div class="tnf">
    <h3 class="tnf-heading">{t('themes.page.note.heading')}</h3>
    <p class="tnf-explain">{t('themes.page.note.explain')}</p>

    <label class="tnf-field">
        <span class="tnf-label">{t('themes.page.note.label')}</span>
        <textarea
            class="tnf-box"
            rows="3"
            maxlength={MAX_NOTE_CHARS}
            disabled={!signedIn || sending}
            bind:value={words}
            oninput={() => {
                sent = false;
                failure = null;
            }}
        ></textarea>
        <span class="tnf-count">{t('themes.page.note.count', { count: words.length, max: MAX_NOTE_CHARS })}</span>
    </label>

    <div class="tnf-acts">
        <button type="button" class="modal-btn modal-btn-confirm" disabled={!submittable} onclick={() => void submit()}>
            {sending ? t('themes.page.note.sending') : t('themes.page.note.send')}
        </button>
    </div>

    {#if !signedIn}
        <p class="tnf-note">
            {t('themes.page.note.signed_out')}
            <button type="button" class="tnf-signin" onclick={() => openCatalogScreen()}>
                {t('themes.page.note.signin')}
            </button>
        </p>
    {/if}

    {#if sent}
        <p class="tnf-note" role="status">{t('themes.page.note.sent')}</p>
    {/if}

    {#if failure}
        <p class="tnf-note tnf-note--out" role="status">
            {t('themes.page.note.failed', { reason: failure })}
        </p>
    {/if}
</div>

<style>
    .tnf {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .tnf :global(.modal-btn) {
        padding: 7px 16px;
        font-size: 13px;
    }

    .tnf-heading {
        margin: 0;
        font-size: 10px;
        font-family: var(--cat-mono);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--cat-muted);
    }

    .tnf-explain {
        margin: 0;
        font-size: 11px;
        line-height: 1.45;
        color: var(--cat-faint);
    }

    .tnf-field {
        display: flex;
        flex-direction: column;
        gap: 3px;
    }

    .tnf-label {
        font-size: 11px;
        color: var(--cat-muted);
    }

    .tnf-box {
        width: 100%;
        box-sizing: border-box;
        padding: 5px 7px;
        border: 1px solid var(--cat-line);
        border-radius: 3px;
        background: var(--cat-raised);
        color: var(--cat-text);
        font-family: inherit;
        font-size: 12px;
        line-height: 1.45;
        resize: vertical;
    }

    .tnf-box:disabled {
        opacity: 0.55;
        cursor: default;
    }

    .tnf-count {
        align-self: flex-end;
        font-family: var(--cat-mono);
        font-size: 10px;
        color: var(--cat-faint);
    }

    .tnf-acts {
        display: flex;
    }


    .tnf-signin {
        padding: 2px 8px;
        border: 1px solid var(--cat-line);
        border-radius: 3px;
        background: transparent;
        color: var(--cat-action);
        font-size: 11px;
        cursor: pointer;
    }

    .tnf-signin:hover {
        background: var(--cat-raised);
    }

    .tnf-note {
        margin: 0;
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 11px;
        line-height: 1.45;
        color: var(--cat-muted);
    }

    .tnf-note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
    }

    @media (max-width: 767px) {
        .tnf-send {
            min-height: 44px;
            padding: 0 16px;
        }

        .tnf-signin {
            min-height: 32px;
        }
    }
</style>
