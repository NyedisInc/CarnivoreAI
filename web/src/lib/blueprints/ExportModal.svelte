
<script lang="ts">
    import ModalShell from '../launchpad/ModalShell.svelte';
    import { t } from '../i18n/index.svelte';
    import ProjectPicker from './ProjectPicker.svelte';
    import { blueprintError, exportBlueprint } from './api';

    interface Props {
        uuid: string;
        close: (value: boolean | null) => void;
    }

    let { uuid, close }: Props = $props();

    let projectPath = $state<string | null>(null);
    let busy = $state(false);
    let error = $state('');
    let done = $state('');

    async function submit(): Promise<void> {
        if (!projectPath || busy) return;
        busy = true;
        error = '';
        try {
            const result = await exportBlueprint(uuid, projectPath);
            done = t('blueprint.export.done', { path: result.path });
        } catch (err) {
            error = t('blueprint.export.failed', { reason: blueprintError(err).detail });
        }
        busy = false;
    }
</script>

<ModalShell title={t('blueprint.export')} dismissable={!busy} onCancel={() => close(!!done)}>
    <div class="modal-input-group">
        <label class="modal-label" for="bp-export-project">{t('blueprint.export')}</label>
        <ProjectPicker id="bp-export-project" value={projectPath} onChange={(p) => (projectPath = p)} />
    </div>
    {#if error}
        <p class="bp-modal__error" role="alert">{error}</p>
    {/if}
    {#if done}
        <p class="bp-modal__ok">{done}</p>
    {/if}
    {#snippet footer()}
        <button class="modal-btn modal-btn-secondary" disabled={busy} onclick={() => close(!!done)}>{t('blueprint.cancel')}</button>
        <button class="modal-btn modal-btn-primary" disabled={busy || !projectPath || !!done} onclick={() => void submit()}>
            {t('blueprint.export')}
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

    .bp-modal__ok {
        margin: 10px 0 0;
        color: var(--oc-text-primary);
        font-size: 12px;
    }
  }
</style>
