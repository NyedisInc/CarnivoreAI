<script lang="ts">
  import { t } from '../sdk';
  import { openArtifact, openArtifactInTab } from './task-manager-artifact.svelte';
  import type { TaskManagerArtifact } from './huddle-model';
  import { sizeLabel } from './task-manager-files';

  let { itemId, artifact }: { itemId: number; artifact: TaskManagerArtifact } = $props();
</script>

<div class="hda" data-task-manager-artifact={artifact.id}>
  <div class="hda-text">
    <span class="hda-title">{artifact.title}</span>
    {#if artifact.description}<span class="hda-desc">{artifact.description}</span>{/if}
    <span class="hda-size">{sizeLabel(artifact.size)}</span>
  </div>
  <button type="button" class="modal-btn modal-btn-secondary hda-open" data-task-manager-artifact-tab={artifact.id}
          aria-label={t('cplug.huddle.artifact.open_in_tab_named', { title: artifact.title })}
          onclick={() => void openArtifactInTab(itemId, artifact)}>{t('cplug.huddle.artifact.open_in_tab')}</button>
  <button type="button" class="modal-btn modal-btn-secondary hda-open" data-task-manager-artifact-open={artifact.id}
          aria-label={t('cplug.huddle.artifact.open_named', { title: artifact.title })}
          onclick={() => void openArtifact(itemId, artifact)}>{t('cplug.huddle.artifact.open')}</button>
</div>

<style>
  @layer components {
    .hda {
      display: flex;
      align-items: center;
      gap: var(--oc-space-3);
      min-width: 0;
      margin: var(--oc-space-1) 0 0;
      padding: var(--oc-space-2) var(--oc-space-3);
      border: 1px solid var(--oc-control-line);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-field);
      font-family: var(--font-mono);
    }

    .hda-text {
      display: flex;
      flex: 1;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }

    .hda-title {
      overflow: hidden;
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-label);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hda-desc {
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-micro);
      overflow-wrap: anywhere;
    }

    .hda-size {
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
    }

    .hda-open {
      flex: none;
    }
  }
</style>
