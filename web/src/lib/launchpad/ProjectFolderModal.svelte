<!-- CANNOT DETERMINE -->
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import {
        PROJECT_CREATE_KEYS,
        nameRefusal,
    } from '../../../../client/js/labels/project-create.js';
    import type { Translate } from '../sessions/types';
    import type { FolderChoice } from './modal-types';
    import { validateName } from './project-folder';
    import ModalShell from './ModalShell.svelte';
    import IconButton from '../base/IconButton.svelte';

    interface Props {
        name: string;
        defaultParent: () => Promise<string | null>;
        openPicker: (() => Promise<string | null>) | null;
        remote?: { label: string; creates?: boolean; browse?: Promise<string | null> } | null;
        confirmLabel?: string;
        t?: Translate;
        close: (value: FolderChoice | null) => void;
    }

    let { name, defaultParent, openPicker, remote = null, confirmLabel, t = reactiveT, close }: Props = $props();

    let parent = $state('');
    let placeholder = $state('');
    let pickerProblem = $state(false);
    let remoteBrowse = $state<'off' | 'checking' | 'ok'>('off');
    let remoteNote = $state('');
    let parentEl: HTMLInputElement | null = $state(null);

    const verdict = $derived(validateName(name));
    const refusal = $derived(nameRefusal(verdict, t));
    const path = $derived(parent.trim());
    const ready = $derived(verdict.ok && parent.trim().length > 0);

    const status = $derived.by(() => {
        if (pickerProblem) {
            return { text: t(PROJECT_CREATE_KEYS.folderPickerUnavailable), error: true };
        }
        if (refusal) return { text: refusal, error: true };
        if (remoteNote) return { text: remoteNote, error: false };
        if (!parent.trim()) {
            return { text: t(PROJECT_CREATE_KEYS.folderChoosePrompt), error: false };
        }
        return { text: '', error: false };
    });

    $effect(() => {
        let live = true;
        placeholder = t(PROJECT_CREATE_KEYS.folderParentLoading);
        defaultParent()
            .then((dir) => {
                if (!live) return;
                if (dir && !parent) parent = dir;
                else if (!dir) placeholder = t(PROJECT_CREATE_KEYS.folderParentUnavailable);
            })
            .catch(() => {
                // CANNOT DETERMINE
                if (live) placeholder = t(PROJECT_CREATE_KEYS.folderParentUnavailable);
            });
        const timer = setTimeout(() => parentEl?.focus(), 100);
        return () => {
            live = false;
            clearTimeout(timer);
        };
    });

    $effect(() => {
        let live = true;
        const pending = remote?.browse;
        remoteNote = '';
        remoteBrowse = pending ? 'checking' : 'off';
        pending
            ?.then((note) => {
                if (!live) return;
                remoteBrowse = note ? 'off' : 'ok';
                remoteNote = note ?? '';
            })
            .catch(() => {
                if (!live) return;
                remoteBrowse = 'off';
                remoteNote = t(PROJECT_CREATE_KEYS.remoteBrowseUnreachable, { computer: remote?.label ?? '' });
            });
        return () => {
            live = false;
        };
    });

    async function browse(): Promise<void> {
        if (!openPicker) {
            pickerProblem = true;
            return;
        }
        const picked = await openPicker();
        if (picked) {
            pickerProblem = false;
            parent = picked;
        }
    }

    function confirm(): void {
        if (!ready) return;
        close({ parent: parent.trim(), path });
    }
</script>

<ModalShell
    title={t(PROJECT_CREATE_KEYS.folderTitle)}
    overlayClass="text-prompt-modal na-flow"
    onCancel={() => close(null)}
>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {t(PROJECT_CREATE_KEYS.folderTitle)}</span>
            <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close
                onclick={() => close(null)} />
        </div>
    {/snippet}
    <div class="modal-input-group">
        <label class="modal-label" for="project-parent-input"
            >{t(PROJECT_CREATE_KEYS.folderParentLabel)}</label
        >
        <input
            type="text"
            class="modal-input"
            id="project-parent-input"
            {placeholder}
            autocomplete="off"
            spellcheck="false"
            bind:this={parentEl}
            bind:value={parent}
        />
        <div class="modal-description">{remote ? t(remote.creates ? PROJECT_CREATE_KEYS.folderRemoteHint : PROJECT_CREATE_KEYS.folderSshHint, { computer: remote.label }) : t(PROJECT_CREATE_KEYS.folderParentHint)}</div>
    </div>
    <div class="modal-input-group">
        <div class="folder-picker-path" id="project-path-preview">
            {path || t(PROJECT_CREATE_KEYS.folderNoPath)}
        </div>
        <div
            class="folder-picker-status"
            class:folder-picker-status--error={status.error}
            id="project-path-status"
            role="status"
            aria-live="polite"
        >
            {status.text}
        </div>
    </div>
    {#snippet footer()}
        <button
            class="modal-btn modal-btn-secondary"
            id="project-folder-cancel"
            onclick={() => close(null)}>{t(PROJECT_CREATE_KEYS.cancel)}</button
        >
        {#if !remote || remoteBrowse === 'ok'}
            <button class="modal-btn modal-btn-secondary" id="project-folder-browse" onclick={browse}
                >{t(PROJECT_CREATE_KEYS.folderBrowse)}</button
            >
        {/if}
        <button
            class="modal-btn modal-btn-confirm"
            id="project-folder-confirm"
            disabled={!ready}
            onclick={confirm}>{confirmLabel ?? t(PROJECT_CREATE_KEYS.confirmCreate)}</button
        >
    {/snippet}
</ModalShell>
