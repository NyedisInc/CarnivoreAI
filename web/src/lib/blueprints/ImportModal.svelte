
<script lang="ts">
    import ModalShell from '../launchpad/ModalShell.svelte';
    import { t } from '../i18n/index.svelte';
    import ProjectPicker from './ProjectPicker.svelte';
    import { blueprintError, importBlueprint } from './api';
    import type { Blueprint } from './types';

    interface Props {
        onImported: (blueprint: Blueprint) => void;
        close: (value: boolean | null) => void;
    }

    let { onImported, close }: Props = $props();

    let projectPath = $state<string | null>(null);
    let name = $state('');
    let busy = $state(false);
    let error = $state('');

    async function submit(): Promise<void> {
        if (!projectPath || busy) return;
        busy = true;
        error = '';
        try {
            const blueprint = await importBlueprint(projectPath, name.trim() || undefined);
            busy = false;
            onImported(blueprint);
            close(true);
        } catch (err) {
            busy = false;
            const refusal = blueprintError(err);
            error =
                refusal.code === 'swarm_file_missing'
                    ? t('blueprint.import.missing')
                    : refusal.code === 'blueprint_name_taken'
                      ? t('blueprint.error.name_taken')
                      : t('blueprint.import.failed', { reason: refusal.detail });
        }
    }
</script>

<ModalShell title={t('blueprint.import')} dismissable={!busy} onCancel={() => close(false)}>
    <div class="modal-input-group">
        <label class="modal-label" for="bp-import-project">{t('blueprint.import')}</label>
        <ProjectPicker id="bp-import-project" value={projectPath} onChange={(p) => (projectPath = p)} />
    </div>
    <div class="modal-input-group">
        <label class="modal-label" for="bp-import-name">{t('blueprint.name.label')}</label>
        <input
            id="bp-import-name"
            type="text"
            class="modal-input"
            maxlength={120}
            placeholder={t('blueprint.name.placeholder')}
            disabled={busy}
            bind:value={name}
        />
    </div>
    {#if error}
        <p class="bp-modal__error" role="alert">{error}</p>
    {/if}
    {#snippet footer()}
        <button class="modal-btn modal-btn-secondary" disabled={busy} onclick={() => close(false)}>{t('blueprint.cancel')}</button>
        <button class="modal-btn modal-btn-primary" disabled={busy || !projectPath} onclick={() => void submit()}>
            {t('blueprint.import')}
        </button>
    {/snippet}
</ModalShell>

<style>
  @layer components {
    .bp-modal__error {
        margin: 10px 0 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-coral);
        background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-raised));
        font-size: 12px;
    }
  }
</style>
