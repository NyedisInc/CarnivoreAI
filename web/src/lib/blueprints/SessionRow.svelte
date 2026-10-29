
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import { Button, Field, RadioGroup } from '../base';
    import SkillsPicker from './SkillsPicker.svelte';
    import type { AccountOption, ProfileRow } from '../launch-profiles-page/api';
    import LaunchProfileDropdown from '../launch-picker/LaunchProfileDropdown.svelte';
    import { initialSelection, rowsFromProfiles } from '../launch-picker/picker-model';
    import type { SessionSpec, WorktreeFolder } from './types';

    interface Props {
        session: SessionSpec;
        index: number;
        onChange: (session: SessionSpec) => void;
        onRemove: () => void;
        removable: boolean;
        profiles?: readonly ProfileRow[];
        accounts?: readonly AccountOption[];
    }

    let { session, index, onChange, onRemove, removable, profiles = [], accounts = [] }: Props = $props();

    const pickerRows = $derived(rowsFromProfiles(profiles, accounts, {
        followActive: t('launch_profiles.list.follow'), modelDefault: t('launch_picker.model_default'), modelAsk: t('launch_picker.model_ask'),
    }));
    const pickedValue = $derived(
        pickerRows.some((r) => r.value === session.family)
            ? session.family
            : initialSelection(pickerRows, { harness: session.family }).value,
    );

    const idPrefix = $derived(`bp-session-${index}`);

    function patch(fields: Partial<SessionSpec>): void {
        onChange({ ...session, ...fields });
    }

    function worktreeFolder(): WorktreeFolder {
        return session.folder.mode === 'worktree'
            ? session.folder
            : { mode: 'worktree', repo_path: '', base_branch: 'master', branch: '' };
    }

    function setFolderMode(mode: 'existing' | 'worktree'): void {
        if (mode === session.folder.mode) return;
        if (mode === 'existing') {
            patch({ folder: { mode: 'existing', path: '' } });
        } else {
            patch({ folder: { mode: 'worktree', repo_path: '', base_branch: 'master', branch: '' } });
        }
    }
</script>

<div class="bp-row" data-session-row={index}>
    <div class="bp-row__head">
        
        <span class="oc-label">{t('blueprint.session.family')} {index + 1}</span>
        {#if removable}
            <Button variant="danger" size="sm" data-bp-session-remove onclick={onRemove}>{t('blueprint.session.remove')}</Button>
        {/if}
    </div>

    <div class="bp-row__grid">
        <label class="modal-label" for={`${idPrefix}-label`}>{t('blueprint.session.label')}</label>
        <Field
            block
            id={`${idPrefix}-label`}
            maxlength={120}
            value={session.label}
            oninput={(e) => patch({ label: (e.currentTarget as HTMLInputElement).value })}
        />

        <span class="modal-label" id={`${idPrefix}-family-label`}>{t('blueprint.session.family')}</span>
        <div class="bp-row__picker" data-bp-launch-picker>
            <LaunchProfileDropdown
                rows={pickerRows}
                value={pickedValue}
                label={t('blueprint.session.family')}
                compact
                onchange={(family) => {
                    const harness = pickerRows.find((r) => r.value === family)?.harness;
                    patch(harness === 'shell' ? { family, opening_prompt: null } : { family });
                }}
            />
        </div>

        <label class="modal-label" for={`${idPrefix}-model`}>{t('blueprint.session.model')}</label>
        <Field
            block
            id={`${idPrefix}-model`}
            placeholder={t('blueprint.session.model.placeholder')}
            value={session.model ?? ''}
            oninput={(e) => patch({ model: (e.currentTarget as HTMLInputElement).value.trim() || null })}
        />

        <span class="modal-label">{t('blueprint.session.folder')}</span>
        <div class="bp-row__folder-mode">
            <RadioGroup
                label={t('blueprint.session.folder')}
                orientation="horizontal"
                name={`${idPrefix}-folder-mode`}
                value={session.folder.mode}
                onchange={(mode) => setFolderMode(mode === 'worktree' ? 'worktree' : 'existing')}
                options={[
                    { value: 'existing', label: t('blueprint.session.folder.existing') },
                    { value: 'worktree', label: t('blueprint.session.folder.worktree') },
                ]}
            />
        </div>

        {#if session.folder.mode === 'existing'}
            <label class="modal-label" for={`${idPrefix}-path`}>{t('blueprint.session.folder.path')}</label>
            <Field
                block
                id={`${idPrefix}-path`}
                value={session.folder.path}
                oninput={(e) => patch({ folder: { mode: 'existing', path: (e.currentTarget as HTMLInputElement).value } })}
            />
        {:else}
            <label class="modal-label" for={`${idPrefix}-repo`}>{t('blueprint.session.folder.repo')}</label>
            <Field
                block
                id={`${idPrefix}-repo`}
                value={session.folder.repo_path}
                oninput={(e) =>
                    patch({
                        folder: { ...worktreeFolder(), repo_path: (e.currentTarget as HTMLInputElement).value },
                    })}
            />

            <label class="modal-label" for={`${idPrefix}-base`}>{t('blueprint.session.folder.base_branch')}</label>
            <Field
                block
                id={`${idPrefix}-base`}
                value={session.folder.base_branch}
                oninput={(e) =>
                    patch({
                        folder: { ...worktreeFolder(), base_branch: (e.currentTarget as HTMLInputElement).value },
                    })}
            />

            <label class="modal-label" for={`${idPrefix}-branch`}>{t('blueprint.session.folder.branch')}</label>
            <Field
                block
                id={`${idPrefix}-branch`}
                value={session.folder.branch}
                oninput={(e) =>
                    patch({
                        folder: { ...worktreeFolder(), branch: (e.currentTarget as HTMLInputElement).value },
                    })}
            />
        {/if}

        <span class="modal-label">{t('blueprint.session.skills')}</span>
        <SkillsPicker skills={session.skills} onChange={(skills) => patch({ skills })} {idPrefix} />

        {#if session.family !== 'shell'}
            
            <label class="modal-label" for={`${idPrefix}-prompt`}>{t('blueprint.session.prompt')}</label>
            <Field
                block
                multiline
                id={`${idPrefix}-prompt`}
                rows={2}
                maxlength={8192}
                placeholder={t('blueprint.session.prompt.placeholder')}
                value={session.opening_prompt ?? ''}
                oninput={(e) => patch({ opening_prompt: (e.currentTarget as HTMLInputElement).value || null })}
            />
        {/if}
    </div>
</div>

<style>
    .bp-row {
        border-top: 1px solid var(--oc-border);
        padding: 10px 0;
    }

    .bp-row:first-child {
        border-top: none;
    }

    .bp-row__head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 6px;
    }

    .bp-row__grid {
        display: grid;
        grid-template-columns: 120px 1fr;
        gap: 6px 10px;
        align-items: start;
    }

    .bp-row__grid > .modal-label {
        padding-top: 6px;
    }

    .bp-row__folder-mode {
        display: flex;
        gap: 14px;
        align-items: center;
        padding-top: 6px;
    }

    .bp-row__picker { min-width: 0; }
</style>
