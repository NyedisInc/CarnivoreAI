<script lang="ts">
  import { onDestroy } from 'svelte';
  import { ApiError, downloadBlob, t, truncatedTip } from '../sdk';
  import { AnchoredPopup, Icon, IconButton, List, ListRow } from '../sdk/ui';
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
  <IconButton label={t('cplug.reviewboard.attachments.key', { count: files.length })} variant="quiet" aria-expanded={open} data-attachments-key
              bind:element={keyEl} onclick={() => (open = !open)}><Icon name="paperclip" size={16} />{#if files.length > 0}<span class="rb-clip-count" data-attachments-count>{files.length}</span>{/if}</IconButton>
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
        <List density="dense">
          {#each shown as file (file.file_id)}
            <ListRow wrap data-attachment={file.file_id}>
              {#snippet primary()}<span data-clip-name use:truncatedTip={file.name}>{file.name}</span>{/snippet}
              {#snippet secondary()}<span data-clip-meta>{t(file.revision ? 'cplug.reviewboard.attachments.meta_rev' : 'cplug.reviewboard.attachments.meta',
                { size: sizeLabel(file.bytes), date: dateLabel(file.added_at), revision: file.revision ?? '' })}</span>
                {#if fileFailed === file.file_id}<span class="rb-clip-error" data-clip-meta role="status">{t('cplug.reviewboard.attachments.file_failed')}</span>{/if}{/snippet}
              {#snippet actions()}
                {#if apiPathOf(file.url)}
                  <IconButton label={t('cplug.reviewboard.attachments.open', { name: file.name })} icon="external" variant="quiet" iconSize={14}
                              data-attachment-open onclick={() => void openFile(file)} />
                  <IconButton label={t('cplug.reviewboard.attachments.download', { name: file.name })} icon="import" variant="quiet" iconSize={14}
                              data-attachment-download onclick={() => void saveFile(file)} />
                {:else}
                  <span class="rb-clip-offline" data-attachment-offline>{t('cplug.reviewboard.attachments.offline')}</span>
                {/if}
              {/snippet}
            </ListRow>
          {/each}
        </List>
      {/if}
    </AnchoredPopup>
  {/if}
</span>