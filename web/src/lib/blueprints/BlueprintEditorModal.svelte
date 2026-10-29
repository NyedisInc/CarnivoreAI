
<script lang="ts">
    import { onMount } from 'svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import { t } from '../i18n/index.svelte';
    import SessionRow from './SessionRow.svelte';
    import { createLaunchProfilesApi, type AccountOption, type ProfileRow } from '../launch-profiles-page/api';
    import { blueprintError, createBlueprint, updateBlueprint } from './api';
    import { blankSession, type Blueprint, type BlueprintSpec, type SessionSpec } from './types';

    const NAME_MAX = 60;
    const SESSIONS_MAX = 16;

    interface Props {
        uuid: string | null;
        initial: BlueprintSpec | null;
        onSaved: (blueprint: Blueprint) => void;
        close: (value: boolean | null) => void;
    }

    let { uuid, initial, onSaved, close }: Props = $props();

    // svelte-ignore state_referenced_locally
    let name = $state(initial?.name ?? '');
    // svelte-ignore state_referenced_locally
    let sessions = $state<SessionSpec[]>(
        initial?.sessions && initial.sessions.length > 0 ? initial.sessions.map((s) => ({ ...s, folder: { ...s.folder }, skills: [...s.skills] })) : [blankSession('agent 1')],
    );
    let error = $state('');
    let busy = $state(false);
    let nameField: HTMLInputElement | null = $state(null);
    let profiles = $state<ProfileRow[]>([]);
    let accounts = $state<AccountOption[]>([]);

    onMount(() => {
        const timer = setTimeout(() => nameField?.focus(), 100);
        const api = createLaunchProfilesApi();
        void api.list().then((body) => { profiles = body.profiles; }).catch((error) => console.warn('blueprint editor: launch profiles unreadable', error));
        void api.accounts().then((list) => { accounts = list; }).catch(() => undefined);
        return () => clearTimeout(timer);
    });

    function addSession(): void {
        if (sessions.length >= SESSIONS_MAX) return;
        sessions = [...sessions, blankSession(`agent ${sessions.length + 1}`)];
    }

    function updateSession(index: number, next: SessionSpec): void {
        sessions = sessions.map((s, i) => (i === index ? next : s));
    }

    function removeSession(index: number): void {
        if (sessions.length <= 1) return;
        sessions = sessions.filter((_, i) => i !== index);
    }

    function folderProblem(session: SessionSpec): string {
        if (session.folder.mode === 'existing' && !session.folder.path.trim()) {
            return t('blueprint.session.folder.path');
        }
        if (session.folder.mode === 'worktree' && (!session.folder.repo_path.trim() || !session.folder.branch.trim())) {
            return t('blueprint.session.folder.worktree');
        }
        return '';
    }

    function localProblem(): string {
        const trimmed = name.trim();
        if (!trimmed) return t('blueprint.error.invalid', { reason: t('blueprint.name.label') });
        if (trimmed.length > NAME_MAX) return t('blueprint.error.invalid', { reason: `> ${NAME_MAX}` });
        if (sessions.length === 0) return t('blueprint.error.no_sessions');
        for (const [index, session] of sessions.entries()) {
            const problem = folderProblem(session);
            if (problem) {
                return t('blueprint.error.invalid', { reason: `${session.label || `${t('blueprint.session.family')} ${index + 1}`}: ${problem}` });
            }
        }
        return '';
    }

    async function submit(): Promise<void> {
        if (busy) return;
        const refused = localProblem();
        if (refused) {
            error = refused;
            return;
        }
        busy = true;
        error = '';
        const spec: BlueprintSpec = {
            version: 1,
            name: name.trim(),
            shape_template: null,
            sessions,
        };
        try {
            const saved = uuid ? await updateBlueprint(uuid, spec) : await createBlueprint(spec);
            busy = false;
            onSaved(saved);
            close(true);
        } catch (err) {
            busy = false;
            const refusal = blueprintError(err);
            error = t('blueprint.save_failed', { reason: refusal.detail });
        }
    }
</script>

<ModalShell
    title={uuid ? t('blueprint.edit') : t('blueprint.new')}
    dismissable={!busy}
    onCancel={() => close(false)}
    overlayClass="bp-editor-overlay"
>
    <div class="modal-input-group">
        <label class="modal-label" for="bp-name">{t('blueprint.name.label')}</label>
        <input
            id="bp-name"
            type="text"
            class="modal-input"
            maxlength={NAME_MAX * 2}
            placeholder={t('blueprint.name.placeholder')}
            bind:this={nameField}
            bind:value={name}
        />
    </div>

    <div class="bp-sessions">
        <div class="bp-sessions__head">
            <span class="oc-label">{t('blueprint.session.heading')}</span>
            <button type="button" class="modal-btn modal-btn-secondary" disabled={sessions.length >= SESSIONS_MAX} onclick={addSession}>
                {t('blueprint.session.add')}
            </button>
        </div>
        {#each sessions as session, index (index)}
            <SessionRow
                {session}
                {index}
                {profiles}
                {accounts}
                removable={sessions.length > 1}
                onChange={(next) => updateSession(index, next)}
                onRemove={() => removeSession(index)}
            />
        {/each}
    </div>

    {#if error}
        <p class="bp-editor__error" role="alert">{error}</p>
    {/if}

    {#snippet footer()}
        <button class="modal-btn modal-btn-secondary" disabled={busy} onclick={() => close(false)}>{t('blueprint.cancel')}</button>
        <button class="modal-btn modal-btn-primary" disabled={busy} onclick={() => void submit()}>{t('blueprint.save')}</button>
    {/snippet}
</ModalShell>

<style>
    :global(.bp-editor-overlay .modal-content) {
        max-width: 640px;
        max-height: 88vh;
        display: flex;
        flex-direction: column;
    }

    :global(.bp-editor-overlay .modal-body) {
        overflow-y: auto;
        min-height: 0;
    }

    .bp-sessions {
        margin-top: 12px;
    }

    .bp-sessions__head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 6px;
    }

    .bp-editor__error {
        margin: 10px 0 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-coral);
        background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-raised));
        color: var(--oc-text-primary);
        font-size: 12px;
        line-height: 1.45;
    }
</style>
