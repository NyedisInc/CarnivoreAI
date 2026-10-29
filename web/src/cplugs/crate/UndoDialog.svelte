
<script lang="ts">
    import { t as reactiveT, type Translate } from '../sdk';
    import { ModalShell } from '../sdk/ui';
    import { errorSentence, type Fetcher } from './crate-api';
    import TtyBox from './TtyBox.svelte';
    import {
        fetchUndoPreview, keptWhy, undoBlockers, undoBlockerSentence, undoImport, type UndoOutcome, type UndoPreview,
    } from './undo-api';
    import './crate-dialog.css';

    interface Props {
        importId: string;
        name: string;
        close: (value: boolean | null) => void;
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { importId, name, close, t = reactiveT, fetcher }: Props = $props();

    let preview = $state<UndoPreview | null>(null);
    let outcome = $state<UndoOutcome | null>(null);
    let busy = $state(false);
    let problem = $state('');
    let blocked = $state<string[]>([]);

    async function read(): Promise<void> {
        try {
            preview = await fetchUndoPreview(importId, fetcher);
        } catch (error) {
            problem = errorSentence(error, t);
        }
    }

    async function go(): Promise<void> {
        busy = true;
        problem = '';
        blocked = [];
        try {
            outcome = await undoImport(importId, fetcher);
        } catch (error) {
            blocked = undoBlockers(error).map((b) => undoBlockerSentence(b, t));
            problem = blocked.length ? '' : errorSentence(error, t);
        } finally {
            busy = false;
        }
    }

    void read();

    const blockers = $derived((preview?.blockers ?? []).map((b) => undoBlockerSentence(b, t)));
    const stays = $derived(outcome ? outcome.kept : (preview?.kept ?? []));
</script>

<ModalShell title={t('cplug.crate.undo.title', { subject: name })} overlayClass="text-prompt-modal crt-modal" dismissable={!busy} onCancel={() => close(outcome ? true : null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">{t('cplug.crate.undo.title', { subject: name })}</span>
            <button type="button" class="modal-close" aria-label={t('modal.close')} onclick={() => close(outcome ? true : null)}>×</button>
        </div>
    {/snippet}
    {#if outcome}
        <p class="modal-description" data-crt-undo-done>
            {t('cplug.crate.undo.done', { rows: outcome.rowsDeleted, files: outcome.filesRemoved, folders: outcome.foldersRemoved })}
        </p>
        {#each outcome.errors as error (error)}<p class="tm__problem" role="alert" data-crt-undo-error>{error}</p>{/each}
    {:else if preview}
        <p class="modal-description" data-crt-undo-body>{t('cplug.crate.undo.body', { name, rows: preview.rowsToRemove, files: preview.files, folders: preview.folders })}</p>
        <p class="tm__sub" data-crt-undo-stays>{t('cplug.crate.undo.stays')}</p>
    {:else if !problem}
        <p class="tm__sub" data-crt-undo-reading>{t('cplug.crate.undo.reading')}</p>
    {/if}
    {#if stays.length}
        <TtyBox label={t('cplug.crate.undo.kept_label')} fit>
            <div class="crt-tty__out">
                <section class="crt-tty__sec crt-tty__sec--pair" data-crt-undo-kept>
                    <div class="crt-tty__head"><span>{t('cplug.crate.undo.kept_head')}</span><span class="crt-tty__count">{stays.length}</span></div>
                    {#each stays as item (item.what)}
                        {@const why = keptWhy(item.why, t)}
                        <p class="crt-tty__row"><span class="crt-tty__name">{item.what}</span><span class="crt-tty__fig crt-tty__fig--left">{why}</span></p>
                    {/each}
                </section>
            </div>
        </TtyBox>
    {/if}
    {#each [...blockers, ...blocked] as sentence (sentence)}<p class="tm__problem" role="alert" data-crt-undo-blocker>{sentence}</p>{/each}
    {#if problem}<p class="tm__problem" role="alert" data-crt-problem>{problem}</p>{/if}
    {#snippet footer()}
        {#if outcome}
            <button type="button" class="modal-btn modal-btn-secondary" data-crt-undo-close onclick={() => close(true)}>{t('cplug.crate.undo.close')}</button>
        {:else}
            <button type="button" class="modal-btn modal-btn-secondary" disabled={busy} onclick={() => close(null)}>{t('cplug.crate.undo.cancel')}</button>
            <button type="button" class="modal-btn modal-btn-danger" data-crt-undo-go disabled={busy || !preview?.ok} onclick={() => void go()}>
                {t(busy ? 'cplug.crate.undo.going' : 'cplug.crate.undo.go')}
            </button>
        {/if}
    {/snippet}
</ModalShell>
