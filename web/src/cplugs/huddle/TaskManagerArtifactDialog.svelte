<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../sdk';
  import { artifactDialog, closeArtifact } from './task-manager-artifact.svelte';

  let panel = $state<HTMLElement | null>(null);

  $effect(() => {
    if (artifactDialog.open) void tick().then(() => panel?.focus());
  });

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeArtifact();
    }
  }
</script>

{#if artifactDialog.open}
  <div class="hda-dlg popup-focus" role="dialog" tabindex="-1" bind:this={panel} aria-label={t('cplug.huddle.artifact.dialog', { title: artifactDialog.title })}
       data-task-manager-artifact-dialog onkeydown={onKeydown}>
    <div class="hda-dlg-titlerow">
      <span class="hda-dlg-label">{artifactDialog.title}</span>
      <span class="hda-dlg-keys">
        {#if artifactDialog.url}
          <a class="modal-btn modal-btn-secondary" href={artifactDialog.url} target="_blank" rel="noopener noreferrer"
             data-task-manager-artifact-popout>{t('cplug.huddle.artifact.pop_out')}</a>
        {/if}
        <button type="button" class="modal-btn modal-btn-secondary" data-task-manager-artifact-close onclick={closeArtifact}>{t('cplug.huddle.artifact.close')}</button>
      </span>
    </div>
    <div class="hda-dlg-body">
      {#if artifactDialog.url}
        <iframe class="hda-dlg-frame" sandbox="allow-scripts" referrerpolicy="no-referrer" src={artifactDialog.url}
                title={artifactDialog.title} data-task-manager-artifact-frame></iframe>
      {:else if artifactDialog.failed}
        <p class="hda-dlg-note" data-task-manager-artifact-failed>{t('cplug.huddle.artifact.failed')}</p>
      {:else}
        <p class="hda-dlg-note">{t('cplug.huddle.artifact.loading')}</p>
      {/if}
    </div>
  </div>
{/if}

<style>
  @layer components {
    .hda-dlg {
      position: fixed;
      top: 50%;
      left: 50%;
      z-index: 60;
      display: flex;
      flex-direction: column;
      width: min(72rem, calc(100vw - var(--oc-space-5)));
      height: min(52rem, calc(100vh - var(--oc-space-5)));
      margin: 0;
      padding: 0;
      border-radius: var(--oc-radius-sm);
      overflow: hidden;
      transform: translate(-50%, -50%);
    }

    .hda-dlg-titlerow {
      display: flex;
      flex: none;
      align-items: center;
      justify-content: space-between;
      gap: var(--oc-space-3);
      min-height: var(--oc-space-5);
      padding: 0 var(--oc-space-3);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .hda-dlg-label {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-overflow: ellipsis;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .hda-dlg-keys {
      display: flex;
      flex: none;
      gap: var(--oc-space-2);
    }

    .hda-dlg-body {
      display: flex;
      flex: 1;
      min-height: 0;
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
