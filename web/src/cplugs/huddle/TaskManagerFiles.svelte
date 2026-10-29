<script lang="ts">
  import { onDestroy } from 'svelte';
  import { Icon } from '../sdk/ui';
  import { downloadBlob, openAttachmentLightbox, t } from '../sdk';
  import { fetchFileBlob } from './task-manager-files-api';
  import { sizeLabel } from './task-manager-files';
  import type { TaskManagerFile } from './huddle-model';

  let { itemId, files }: { itemId: number; files: TaskManagerFile[] } = $props();

  let urls = $state<Record<string, string>>({});
  let failed = $state<Record<string, boolean>>({});
  let gone = false;

  $effect(() => {
    for (const file of files) {
      if (!file.image || urls[file.id] || failed[file.id]) continue;
      fetchFileBlob(itemId, file.id).then(
        (blob) => { if (!gone) urls[file.id] = URL.createObjectURL(blob); },
        () => { if (!gone) failed[file.id] = true; },
      );
    }
  });

  onDestroy(() => {
    gone = true;
    for (const url of Object.values(urls)) URL.revokeObjectURL(url);
  });

  async function open(file: TaskManagerFile, button: HTMLElement): Promise<void> {
    openAttachmentLightbox(await fetchFileBlob(itemId, file.id), file.name, button);
  }

  async function save(file: TaskManagerFile): Promise<void> {
    downloadBlob(file.name, await fetchFileBlob(itemId, file.id));
  }
</script>

<ul class="hdf" aria-label={t('cplug.huddle.files.label')} data-task-manager-files={itemId}>
  {#each files as file (file.id)}
    <li class="hdf-one" data-task-manager-file={file.id}>
      {#if file.image && urls[file.id]}
        <button type="button" class="hdf-thumb" data-task-manager-file-open={file.id} aria-label={t('cplug.huddle.files.open', { name: file.name })}
                onclick={(event) => void open(file, event.currentTarget)}><img src={urls[file.id]} alt={file.name} draggable="false" /></button>
      {:else}
        <button type="button" class="hdf-chip" data-task-manager-file-save={file.id} aria-label={t('cplug.huddle.files.save', { name: file.name })}
                onclick={() => void save(file)}>
          <Icon name={file.image ? 'image' : 'files'} size={12} strokeWidth={1.75} />
          <span class="hdf-name">{file.name}</span>
          <span class="hdf-size">{sizeLabel(file.size)}</span>
        </button>
      {/if}
    </li>
  {/each}
</ul>

<style>
  @layer components {
    .hdf {
      display: flex;
      flex-wrap: wrap;
      gap: var(--oc-space-1);
      min-width: 0;
      margin: var(--oc-space-1) 0 0;
      padding: 0;
      list-style: none;
    }

    .hdf-one {
      min-width: 0;
    }

    .hdf-thumb {
      display: block;
      width: calc(var(--oc-space-6) * 2);
      height: calc(var(--oc-space-6) * 2);
      padding: 0;
      overflow: hidden;
      border: 1px solid var(--oc-control-line);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-field);
      cursor: zoom-in;
    }

    .hdf-thumb img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    .hdf-thumb:hover {
      border-color: var(--oc-control-line-hi);
    }

    .hdf-chip {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      max-width: 100%;
      min-width: 0;
      padding: 0 var(--oc-space-2);
      border: 1px solid var(--oc-control-line);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-field);
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      line-height: var(--oc-space-5);
      cursor: pointer;
    }

    .hdf-chip:hover {
      border-color: var(--oc-control-line-hi);
      color: var(--oc-text-primary);
    }

    .hdf-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdf-size {
      flex: none;
      color: var(--oc-text-dim);
    }
  }
</style>
