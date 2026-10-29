
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import { createLaunchProfilesApi } from '../launch-profiles-page/api';
    import { PROJECT_CREATE_KEYS } from '../../../../client/js/labels/project-create.js';
    import type { Translate } from '../sessions/types';
    import type { EditResult } from './modal-types';
    import ModalShell from './ModalShell.svelte';
    import { isProjectColor } from '../project-colors/palette';
    import ProjectColorSwatches from '../project-colors/ProjectColorSwatches.svelte';
    import Check from '../../opscenter/ui/Check.svelte';
    import taskManagerManifest from '../../../../src/cplugs/huddle/cplug.json';
    import { cplugEnabled } from '../../cplugs/host/enablement.svelte';
    import { getListInbox, getListNudge } from '../../cplugs/huddle/task-list-prefs';
    import type { CplugManifest } from '../../cplugs/sdk';

    interface Props {
        projectName: string;
        projectPath: string;
        projectDescription?: string | null;
        projectDefaultLaunchProfile?: string | null;
        projectColor?: string | null;
        projectId?: number | null;
        t?: Translate;
        close: (value: EditResult | null) => void;
    }

    let {
        projectName,
        projectPath,
        projectDescription = '',
        projectDefaultLaunchProfile = '',
        projectColor = '',
        projectId = null,
        t = reactiveT,
        close,
    }: Props = $props();

    // svelte-ignore state_referenced_locally
    let name = $state(projectName);
    // svelte-ignore state_referenced_locally
    let description = $state(projectDescription || '');
    // svelte-ignore state_referenced_locally
    let defaultProfile = $state(projectDefaultLaunchProfile || '');
    // svelte-ignore state_referenced_locally
    let color = $state(isProjectColor(projectColor) ? projectColor : '');
    let profileOptions = $state<{ id: string; label: string }[]>([]);
    onMount(() => {
        createLaunchProfilesApi().list()
            .then((out) => { profileOptions = out.profiles.map((p) => ({ id: p.id, label: p.label || p.id })); })
            .catch((error) => console.warn('CloudeWeb: launch profiles unreadable for the project default', error));
    });
    const taskManagerOn = $derived(projectId !== null && cplugEnabled(taskManagerManifest as CplugManifest));
    let nudgeStored = $state<boolean | null>(null);
    let nudge = $state(false);
    let inboxStored = $state<boolean | null>(null);
    let inbox = $state(true);
    onMount(() => {
        if (projectId === null || !cplugEnabled(taskManagerManifest as CplugManifest)) return;
        getListNudge(projectId)
            .then((on) => { nudgeStored = on; nudge = on; })
            .catch((error) => console.warn('CloudeWeb: the huddle nudge is unreadable for the edit modal', error));
        getListInbox(projectId)
            .then((on) => { inboxStored = on; inbox = on; })
            .catch((error) => console.warn('CloudeWeb: the huddle add box switch is unreadable for the edit modal', error));
    });
    let nameEl: HTMLInputElement | null = $state(null);
    let descEl: HTMLInputElement | null = $state(null);

    $effect(() => {
        const timer = setTimeout(() => {
            nameEl?.focus();
            nameEl?.select();
        }, 100);
        return () => clearTimeout(timer);
    });

    function submit(): void {
        const trimmed = name.trim();
        if (!trimmed) {
            nameEl?.focus();
            return;
        }
        close({
            name: trimmed, description: description.trim(), defaultLaunchProfile: defaultProfile, color,
            ...(nudgeStored !== null && nudge !== nudgeStored ? { nudge } : {}),
            ...(inboxStored !== null && inbox !== inboxStored ? { inbox } : {}),
        });
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

<ModalShell title={t(PROJECT_CREATE_KEYS.editTitle)} onCancel={() => close(null)}>
    <div class="modal-input-group">
        <div class="modal-label">{t(PROJECT_CREATE_KEYS.folderLabel)}</div>
        <div class="folder-picker-path">{projectPath}</div>
        <div class="modal-description">{t(PROJECT_CREATE_KEYS.editFolderHint)}</div>
    </div>
    <div class="modal-input-group">
        <label class="modal-label" for="edit-project-name"
            >{t(PROJECT_CREATE_KEYS.nameLabel)}</label
        >
        <input
            type="text"
            class="modal-input"
            id="edit-project-name"
            autocomplete="off"
            bind:this={nameEl}
            bind:value={name}
            onkeydown={onNameKey}
        />
    </div>
    <div class="modal-input-group">
        <label class="modal-label" for="edit-project-description"
            >{t(PROJECT_CREATE_KEYS.descriptionLabel)}</label
        >
        <input
            type="text"
            class="modal-input"
            id="edit-project-description"
            placeholder={t(PROJECT_CREATE_KEYS.descriptionPlaceholder)}
            autocomplete="off"
            bind:this={descEl}
            bind:value={description}
            onkeydown={onDescKey}
        />
    </div>
    <div class="modal-input-group">
        <label class="modal-label" for="edit-project-launch-profile">{t('launch_picker.project_default')}</label>
        <select class="modal-input oc-focus-host" id="edit-project-launch-profile" bind:value={defaultProfile}>
            <option value="">{t('launch_picker.project_default_none')}</option>
            {#each profileOptions as option (option.id)}<option value={option.id}>{option.label}</option>{/each}
            {#if defaultProfile && !profileOptions.some((o) => o.id === defaultProfile)}<option value={defaultProfile}>{defaultProfile}</option>{/if}
        </select>
        <div class="modal-description">{t('launch_picker.project_default_hint')}</div>
    </div>
    <div class="modal-input-group">
        <div class="modal-label" id="edit-project-color-label">{t('project.color.label')}</div>
        <ProjectColorSwatches value={color} labelledBy="edit-project-color-label" {t} allowNone onPick={(key) => (color = key)} />
        <div class="modal-description">{t('project.color.hint')}</div>
    </div>
    {#if taskManagerOn && nudgeStored !== null}
        <div class="modal-input-group" data-edit-project-huddle="">
            <div class="modal-label">{t('project.edit.task_manager.label')}</div>
            <Check label={t('project.edit.task_manager.nudge')} checked={nudge} onToggle={(next) => (nudge = next)} data-edit-project-nudge="" />
            <div class="modal-description">{t('project.edit.task_manager.nudge_hint')}</div>
        </div>
    {/if}
    {#if taskManagerOn && inboxStored !== null}
        <div class="modal-input-group" data-edit-project-huddle-inbox="">
            <Check label={t('project.edit.task_manager.inbox')} checked={inbox} onToggle={(next) => (inbox = next)} data-edit-project-inbox="" />
            <div class="modal-description">{t('project.edit.task_manager.inbox_hint')}</div>
        </div>
    {/if}
    {#snippet footer()}
        <button
            class="modal-btn modal-btn-secondary"
            id="edit-modal-cancel"
            onclick={() => close(null)}>{t(PROJECT_CREATE_KEYS.cancel)}</button
        >
        <button class="modal-btn modal-btn-primary" id="edit-modal-save" onclick={submit}
            >{t(PROJECT_CREATE_KEYS.editSave)}</button
        >
    {/snippet}
</ModalShell>
