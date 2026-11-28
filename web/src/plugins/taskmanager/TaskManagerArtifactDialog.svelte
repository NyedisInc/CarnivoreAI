<script lang="ts">
  import { ModalShell } from '../sdk/ui';
  import { t } from '../sdk';
  import { artifactDialog, closeArtifact } from './task-manager-artifact.svelte';

  const WIDTH = 'min(72rem, calc(100vw - var(--oc-space-5)))';
  const HEIGHT = 'min(52rem, calc(100vh - var(--oc-space-5)))';
</script>

{#if artifactDialog.open}
  <ModalShell look="titlerow" fill width={WIDTH} height={HEIGHT} title={t('cplug.huddle.artifact.dialog', { title: artifactDialog.title })}
              label={artifactDialog.title} closeLabel={t('cplug.huddle.artifact.close')} onCancel={closeArtifact} data-task-manager-artifact-dialog>
    {#snippet headExtra()}
      {#if artifactDialog.url}
        <a class="modal-btn modal-btn-secondary hda-dlg-popout" href={artifactDialog.url} target="_blank" rel="noopener noreferrer"
           data-task-manager-artifact-popout>{t('cplug.huddle.artifact.pop_out')}</a>
      {/if}
    {/snippet}
    {#if artifactDialog.url}
      <iframe class="hda-dlg-frame" sandbox="allow-scripts" referrerpolicy="no-referrer" src={artifactDialog.url}
              title={artifactDialog.title} data-task-manager-artifact-frame></iframe>
    {:else if artifactDialog.failed}
      <p class="hda-dlg-note" data-task-manager-artifact-failed>{t('cplug.huddle.artifact.failed')}</p>
    {:else}
      <p class="hda-dlg-note">{t('cplug.huddle.artifact.loading')}</p>
    {/if}
  </ModalShell>
{/if}

<style>
  @layer components {
    .hda-dlg-popout {
      flex: none;
      margin-inline-start: auto;
    }

    .hda-dlg-frame {
      flex: 1;
      width: 100%;
      border: 0;
      color-scheme: light;
      background: Canvas;
    }

    .hda-dlg-note {
      margin: var(--oc-space-3);
      color: var(--oc-text-dim);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
    }
  }
</style>
