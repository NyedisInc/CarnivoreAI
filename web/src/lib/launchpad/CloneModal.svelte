<!-- the project row -->
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import {
        PROJECT_CREATE_KEYS,
        cloneFailure,
    } from '../../../../client/js/labels/project-create.js';
    import type { Translate } from '../sessions/types';
    import type { ClonedProject } from './modal-types';
    import ModalShell from './ModalShell.svelte';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';

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

    let { clone, defaultParentDir = '', confirmLabel, t = reactiveT, close }: Props = $props();

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
        <Field
            label={t(PROJECT_CREATE_KEYS.cloneUrlLabel)}
            help={t(PROJECT_CREATE_KEYS.cloneUrlHint)}
            id="modal-clone-url"
            placeholder={t(PROJECT_CREATE_KEYS.cloneUrlPlaceholder)}
            autocomplete="off"
            spellcheck="false"
            disabled={busy}
            bind:value={repoUrl}
            onkeydown={(e) => onFieldKey(e, repoUrl.trim() ? parentEl : null)}
            bind:element={urlEl}
        />
    </div>
    <div class="modal-input-group">
        <Field
            label={t(PROJECT_CREATE_KEYS.cloneParentLabel)}
            help={t(PROJECT_CREATE_KEYS.cloneParentHint)}
            id="modal-clone-parent"
            placeholder={defaultParentDir || t(PROJECT_CREATE_KEYS.folderParentUnavailable)}
            autocomplete="off"
            spellcheck="false"
            disabled={busy}
            bind:value={parentDir}
            onkeydown={(e) => onFieldKey(e, descEl)}
            bind:element={parentEl}
        />
    </div>
    <div class="modal-input-group">
        <Field
            label={t(PROJECT_CREATE_KEYS.descriptionLabel)}
            id="modal-clone-description"
            placeholder={t(PROJECT_CREATE_KEYS.cloneDescriptionPlaceholder)}
            autocomplete="off"
            disabled={busy}
            bind:value={description}
            onkeydown={(e) => onFieldKey(e, null)}
            bind:element={descEl}
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
        <Button id="modal-clone-cancel" disabled={busy} onclick={() => close(null)}>{t(PROJECT_CREATE_KEYS.cancel)}</Button>
        <Button variant="confirm" id="modal-clone-confirm" disabled={busy} onclick={submit}
            >{confirmLabel ?? t(PROJECT_CREATE_KEYS.cloneConfirm)}</Button
        >
    {/snippet}
</ModalShell>
