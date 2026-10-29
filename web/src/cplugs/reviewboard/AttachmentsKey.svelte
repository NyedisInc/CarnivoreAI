<script lang="ts">
  import { onDestroy } from 'svelte';
  import { ApiError, downloadBlob, t, truncatedTip } from '../sdk';
  import { AnchoredPopup, Icon } from '../sdk/ui';
  import { fetchAttachmentBlob, fetchAttachments } from './board-api';
  import { apiPathOf, dateLabel, openType, sizeLabel, type BoardAttachment } from './attachment-model';

  let { slug, tick }: { slug: string; tick: number } = $props();

  let files = $state<BoardAttachment[]>([]);
  let open = $state(false);
  let keyEl = $state<HTMLElement | null>(null);
  let listFailed = $state(false);
  let fileFailed = $state<string | null>(null);
  const handed: string[] = [];

  const shown = $derived([...files].reverse());

  $effect(() => {
    void tick;
    void load(slug);
  });

  onDestroy(() => {
    for (const url of handed) URL.revokeObjectURL(url);
  });

  async function load(board: string): Promise<void> {
    try {
      const out = await fetchAttachments(board);
      if (board !== slug) return;
      files = out.attachments;
      listFailed = false;
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      if (board === slug) listFailed = true;
    }
  }

  async function openFile(file: BoardAttachment): Promise<void> {
    const path = apiPathOf(file.url);
    if (!path) return;
    const shownAs = openType(file.mime);
    if (shownAs === null) return saveFile(file);
    fileFailed = null;
    const tab = window.open('', '_blank');
    if (tab) tab.opener = null;
    try {
      const bytes = await fetchAttachmentBlob(path);
      const url = URL.createObjectURL(new Blob([bytes], { type: shownAs }));
      handed.push(url);
      if (tab) tab.location.href = url;
      else window.open(url, '_blank', 'noopener');
    } catch (error) {
      tab?.close();
      if (!(error instanceof ApiError)) throw error;
      fileFailed = file.file_id;
    }
  }

  async function saveFile(file: BoardAttachment): Promise<void> {
    const path = apiPathOf(file.url);
    if (!path) return;
    fileFailed = null;
    try {
      downloadBlob(file.name, await fetchAttachmentBlob(path));
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      fileFailed = file.file_id;
    }
  }

  function closeOnEscape(event: KeyboardEvent): void {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      open = false;
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span class="rb-clipwrap" onkeydown={closeOnEscape}>
  <button type="button" class="rb-icon rb-clip-key" aria-label={t('cplug.reviewboard.attachments.key', { count: files.length })}
          title={t('cplug.reviewboard.attachments.key', { count: files.length })} aria-expanded={open} data-attachments-key bind:this={keyEl}
          onclick={() => (open = !open)}><Icon name="paperclip" size={16} />{#if files.length > 0}<span class="rb-clip-count" data-attachments-count>{files.length}</span>{/if}</button>
  {#if open}
    <AnchoredPopup class="rb-clippop" label={t('cplug.reviewboard.attachments.title')} anchor={keyEl} outside="none" initialFocus="none" returnFocus={false}
                   onClose={() => (open = false)} data-attachments-fold>
      <p class="rb-label rb-clippop-head">{t('cplug.reviewboard.attachments.title')}</p>
      {#if listFailed}
        <p class="rb-note rb-note--error" role="status" data-attachments-failed>{t('cplug.reviewboard.attachments.read_failed')}</p>
      {/if}
      {#if shown.length === 0}
        {#if !listFailed}<p class="rb-note-text" data-attachments-empty>{t('cplug.reviewboard.attachments.none')}</p>{/if}
      {:else}
        <ul class="rb-cliplist">
          {#each shown as file (file.file_id)}
            <li class="rb-clip" data-attachment={file.file_id}>
              <span class="rb-clip-text">
                <span class="rb-clip-name" use:truncatedTip={file.name}>{file.name}</span>
                <span class="rb-clip-meta">{t(file.revision ? 'cplug.reviewboard.attachments.meta_rev' : 'cplug.reviewboard.attachments.meta',
                  { size: sizeLabel(file.bytes), date: dateLabel(file.added_at), revision: file.revision ?? '' })}</span>
                {#if fileFailed === file.file_id}<span class="rb-clip-meta rb-clip-meta--error" role="status">{t('cplug.reviewboard.attachments.file_failed')}</span>{/if}
              </span>
              {#if apiPathOf(file.url)}
                <button type="button" class="rb-icon" aria-label={t('cplug.reviewboard.attachments.open', { name: file.name })}
                        title={t('cplug.reviewboard.attachments.open', { name: file.name })} data-attachment-open onclick={() => void openFile(file)}><Icon name="external" size={14} /></button>
                <button type="button" class="rb-icon" aria-label={t('cplug.reviewboard.attachments.download', { name: file.name })}
                        title={t('cplug.reviewboard.attachments.download', { name: file.name })} data-attachment-download onclick={() => void saveFile(file)}><Icon name="import" size={14} /></button>
              {:else}
                <span class="rb-clip-meta" data-attachment-offline>{t('cplug.reviewboard.attachments.offline')}</span>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </AnchoredPopup>
  {/if}
</span>