
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import { PROJECT_CREATE_KEYS } from '../../../../client/js/labels/project-create.js';
    import type { Translate } from '../sessions/types';
    import type { ProjectDetails } from './modal-types';
    import ModalShell from './ModalShell.svelte';
    import IconButton from '../base/IconButton.svelte';

    interface Props {
        title: string;
        confirmLabel: string;
        defaultName?: string;
        pathHint?: string | null;
        t?: Translate;
        close: (value: ProjectDetails | null) => void;
    }

    let {
        title,
        confirmLabel,
        defaultName = '',
        pathHint = null,
        t = reactiveT,
        close,
    }: Props = $props();

    // svelte-ignore state_referenced_locally
    let name = $state(defaultName);
    let description = $state('');
    let nameEl: HTMLInputElement | null = $state(null);
    let descEl: HTMLInputElement | null = $state(null);

    $effect(() => {
        const timer = setTimeout(() => {
            nameEl?.focus();
            if (defaultName) nameEl?.select();
        }, 100);
        return () => clearTimeout(timer);
    });

    function submit(): void {
        const trimmed = name.trim();
        if (!trimmed) {
            nameEl?.focus();
            return;
        }
        close({ name: trimmed, description: description.trim() });
    }

    function onNameKey(event: KeyboardEvent): void {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        if (name.trim()) descEl?.focus();
    }

    function onDescKey(event: KeyboardEvent): void {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        submit();
    }
</script>

<ModalShell {title} overlayClass="text-prompt-modal na-flow" onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {title}</span>
            <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close
                onclick={() => close(null)} />
        </div>
    {/snippet}
    {#if pathHint}
        <div class="modal-input-group">
            <div class="modal-label">{t(PROJECT_CREATE_KEYS.folderLabel)}</div>
            <div class="folder-picker-path">{pathHint}</div>
        </div>
    {/if}
    <div class="modal-input-group">
        <label class="modal-label" for="modal-project-name"
            >{t(PROJECT_CREATE_KEYS.nameLabel)}</label
        >
        <input
            type="text"
            class="modal-input"
            id="modal-project-name"
            placeholder={t(PROJECT_CREATE_KEYS.namePlaceholder)}
            autocomplete="off"
            bind:this={nameEl}
            bind:value={name}
            onkeydown={onNameKey}
        />
        <div class="modal-description">{t(PROJECT_CREATE_KEYS.nameHint)}</div>
    </div>
    <div class="modal-input-group">
        <label class="modal-label" for="modal-project-description"
            >{t(PROJECT_CREATE_KEYS.descriptionLabel)}</label
        >
        <input
            type="text"
            class="modal-input"
            id="modal-project-description"
            placeholder={t(PROJECT_CREATE_KEYS.descriptionPlaceholder)}
            autocomplete="off"
            bind:this={descEl}
            bind:value={description}
            onkeydown={onDescKey}
        />
        <div class="modal-description">{t(PROJECT_CREATE_KEYS.descriptionHint)}</div>
    </div>
    {#snippet footer()}
        <button class="modal-btn modal-btn-secondary" id="modal-cancel" onclick={() => close(null)}
            >{t(PROJECT_CREATE_KEYS.cancel)}</button
        >
        <button class="modal-btn modal-btn-confirm" id="modal-confirm" onclick={submit}
            >{confirmLabel}</button
        >
    {/snippet}
</ModalShell>
