<script lang="ts">
  import { Icon } from '../sdk/ui';
  import { t } from '../sdk';
  import { sizeLabel } from './task-manager-files';
  import type { Chip } from './task-manager-attachments.svelte';

  let { chips, onRemove }: { chips: Chip[]; onRemove: (key: number) => void } = $props();
</script>

<ul class="hdc" aria-label={t('cplug.huddle.files.pending')} data-task-manager-pending-files>
  {#each chips as chip (chip.key)}
    <li class="hdc-chip" data-state={chip.status} data-task-manager-pending-file={chip.key}>
      <Icon name="files" size={12} strokeWidth={1.75} />
      <span class="hdc-name">{chip.name}</span>
      <span class="hdc-state">{chip.status === 'uploading' ? t('cplug.huddle.files.uploading') : chip.status === 'failed' ? (chip.error ?? t('cplug.huddle.files.failed')) : sizeLabel(chip.size)}</span>
      <button type="button" class="oc-ibtn oc-ibtn--bare hdc-remove" data-task-manager-pending-remove={chip.key}
              aria-label={t('cplug.huddle.files.remove', { name: chip.name })}
              onclick={() => onRemove(chip.key)}><Icon name="close" size={12} strokeWidth={1.75} /></button>
    </li>
  {/each}
</ul>

<style>
  @layer components {
    .hdc {
      display: flex;
      flex: 1 1 100%;
      flex-wrap: wrap;
      gap: var(--oc-space-1);
      min-width: 0;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .hdc-chip {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      max-width: 100%;
      min-width: 0;
      padding: 0 0 0 var(--oc-space-2);
      border: 1px solid var(--oc-control-line);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-raised);
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      line-height: var(--oc-space-5);
    }

    .hdc-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdc-state {
      flex: none;
      color: var(--oc-text-dim);
    }

    .hdc-chip[data-state='failed'] {
      border-color: var(--oc-coral);
    }

    .hdc-chip[data-state='failed'] .hdc-state {
      color: var(--oc-coral);
    }

    .hdc-remove {
      flex: none;
    }
  }
</style>
