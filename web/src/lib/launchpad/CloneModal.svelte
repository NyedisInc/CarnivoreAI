<!-- already running the project row -->
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import {
        PROJECT_CREATE_KEYS,
        cloneFailure,
    } from '../../../../client/js/labels/project-create.js';
    import type { Translate } from '../sessions/types';
    import type { ClonedProject } from './modal-types';
    import ModalShell from './ModalShell.svelte';

    interface ClonePayload {
        repoUrl: string;
        parentDir: string;
        description?: string;
    }

    interface Props {
        clone: (payload: ClonePayload) => Promise<ClonedProject>;
        defaultParentDir?: string;
        confirmLabel?: string;
        t?: Translate;
        close: (value: ClonedProject | null) => void;
    }

    let { clone, defaultParentDir = '~/projects', confirmLabel, t = reactiveT, close }: Props = $props();

    let repoUrl = $state('');
    // svelte-ignore state_referenced_locally
    let parentDir = $state(defaultParentDir);
    let description = $state('');
    let status = $state('');
    let statusIsError = $state(false);
    let busy = $state(false);
    let urlEl: HTMLInputElement | null = $state(null);
    let parentEl: HTMLInputElement | null = $state(null);
    let descEl: HTMLInputElement | null = $state(null);

    $effect(() => {
        const timer = setTimeout(() => urlEl?.focus(), 100);
        return () => clearTimeout(timer);
    });

    async function submit(): Promise<void> {
        if (busy) return;
        const url = repoUrl.trim();
        if (!url) {
            status = t(PROJECT_CREATE_KEYS.cloneNeedsUrl);
            statusIsError = true;
            urlEl?.focus();
            return;
        }
        busy = true;
        status = t(PROJECT_CREATE_KEYS.cloneBusy);
        statusIsError = false;
        try {
            const project = await clone({
                repoUrl: url,
                parentDir: parentDir.trim() || defaultParentDir,
                description: description.trim() || undefined,
            });
            close(project);
        } catch (error) {
            console.error('CloneModal: clone-from-github failed:', error);
            status = cloneFailure(error, t);
            statusIsError = true;
            busy = false;
        }
    }

    function onFieldKey(event: KeyboardEvent, next: HTMLInputElement | null): void {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        if (next) {
            next.focus();
            return;
        }
        void submit();
    }
</script>

<ModalShell
    title={t(PROJECT_CREATE_KEYS.cloneTitle)}
    dismissable={!busy}
    onCancel={() => close(null)}
>
    <div class="modal-input-group">
        <label class="modal-label" for="modal-clone-url"
            >{t(PROJECT_CREATE_KEYS.cloneUrlLabel)}</label
        >
        <input
            type="text"
            class="modal-input"
            id="modal-clone-url"
            placeholder={t(PROJECT_CREATE_KEYS.cloneUrlPlaceholder)}
            autocomplete="off"
            spellcheck="false"
            disabled={busy}
            bind:this={urlEl}
            bind:value={repoUrl}
            onkeydown={(e) => onFieldKey(e, repoUrl.trim() ? parentEl : null)}
        />
        <div class="modal-description">{t(PROJECT_CREATE_KEYS.cloneUrlHint)}</div>
    </div>
    <div class="modal-input-group">
        <label class="modal-label" for="modal-clone-parent"
            >{t(PROJECT_CREATE_KEYS.cloneParentLabel)}</label
        >
        <input
            type="text"
            class="modal-input"
            id="modal-clone-parent"
            placeholder={defaultParentDir}
            autocomplete="off"
            spellcheck="false"
            disabled={busy}
            bind:this={parentEl}
            bind:value={parentDir}
            onkeydown={(e) => onFieldKey(e, descEl)}
        />
        <div class="modal-description">{t(PROJECT_CREATE_KEYS.cloneParentHint)}</div>
    </div>
    <div class="modal-input-group">
        <label class="modal-label" for="modal-clone-description"
            >{t(PROJECT_CREATE_KEYS.descriptionLabel)}</label
        >
        <input
            type="text"
            class="modal-input"
            id="modal-clone-description"
            placeholder={t(PROJECT_CREATE_KEYS.cloneDescriptionPlaceholder)}
            autocomplete="off"
            disabled={busy}
            bind:this={descEl}
            bind:value={description}
            onkeydown={(e) => onFieldKey(e, null)}
        />
    </div>
    {#if status}
        <div
            class="modal-description"
            class:folder-picker-status--error={statusIsError}
            id="modal-clone-status"
            role="status"
            aria-live="polite"
        >
            {status}
        </div>
    {/if}
    {#snippet footer()}
        <button
            class="modal-btn modal-btn-secondary"
            id="modal-clone-cancel"
            disabled={busy}
            onclick={() => close(null)}>{t(PROJECT_CREATE_KEYS.cancel)}</button
        >
        <button
            class="modal-btn modal-btn-primary"
            id="modal-clone-confirm"
            disabled={busy}
            onclick={submit}>{confirmLabel ?? t(PROJECT_CREATE_KEYS.cloneConfirm)}</button
        >
    {/snippet}
</ModalShell>
