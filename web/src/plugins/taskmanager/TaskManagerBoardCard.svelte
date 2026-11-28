<script lang="ts">
  import { untrack } from 'svelte';
  import { roundOpener, subscribeBoardFiles, t, type BoardCardFile } from '../sdk';
  import { Card, Icon, IconButton, Tag } from '../sdk/ui';
  import { typeKey } from './board-card-model';
  import type { TaskManagerBoardCard as BoardCard } from './huddle-model';

  let { board }: { board: BoardCard } = $props();

  let files = $state<BoardCardFile[]>([]);
  const canOpen = $derived(roundOpener() !== null);
  const here = $derived(files.filter((f) => f.revision === board.revision));
  const liveCount = $derived(here.filter((f) => !f.removed).length);

  $effect(() => {
    const slug = board.slug;
    return untrack(() => subscribeBoardFiles(slug, (next) => { files = next; }));
  });

  async function open(): Promise<void> {
    try {
      await roundOpener()?.({ slug: board.slug, revision: board.revision });
    } catch {
    }
  }
</script>

<Card compact title={t('cplug.huddle.board.card', { title: board.title || board.slug, revision: board.revision })} headingLevel={4}
      data-task-manager-board={board.slug} data-task-manager-board-revision={board.revision}>
  {#snippet actions()}
    {#if canOpen}
      <IconButton label={t('cplug.huddle.board.open', { revision: board.revision })} variant="quiet" data-task-manager-board-open={board.slug} onclick={() => void open()}>
        <Icon name="external" size={16} />
      </IconButton>
    {/if}
  {/snippet}
  {#snippet children()}
    <div class="hdbc-text">
      {#if board.summary}<span class="hdbc-line" data-task-manager-board-summary>{board.summary}</span>{/if}
      {#if here.length > 0}
        <span class="hdbc-line" data-task-manager-board-count>{t('cplug.huddle.board.files', { count: liveCount })}</span>
        <ul class="hdbc-files">
          {#each here as file (file.file_id)}
            <li class="hdbc-file" class:hdbc-file--removed={file.removed} data-task-manager-board-file={file.file_id}>
              <span class="hdbc-name">{file.name}</span>
              <span class="hdbc-type">{t(typeKey(file.name))}</span>
              {#if file.removed}<Tag tone="neutral">{t('cplug.huddle.board.removed')}</Tag>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/snippet}
</Card>

<style>
  @layer components {
    .hdbc-text { display: flex; flex-direction: column; gap: var(--oc-space-0-5); min-width: 0; }
    .hdbc-line { color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); overflow-wrap: anywhere; }
    .hdbc-files { display: flex; flex-direction: column; gap: var(--oc-space-0-5); margin: 0; padding: 0; list-style: none; }
    .hdbc-file { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oc-space-2); color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); }
    .hdbc-name { overflow-wrap: anywhere; }
    .hdbc-type { color: var(--oc-text-dim); }
    .hdbc-file--removed .hdbc-name { text-decoration: line-through; }
  }
</style>
