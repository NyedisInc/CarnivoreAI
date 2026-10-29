<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import { MAX_BOARDS } from '../engine/home-boards';
  import { homeBoards } from '../engine/home-sync.svelte';
  import { importBoard, previewImport, refusalOf, type ImportPreview } from './board-transfer';

  let { announce }: { announce: (text: string) => void } = $props();

  let input = $state<HTMLInputElement | null>(null);
  let pending = $state<{ document: unknown; preview: ImportPreview } | null>(null);
  let problem = $state<{ message: string; refusals: string[] } | null>(null);
  let busy = $state(false);
  const full = $derived(homeBoards.list.length >= MAX_BOARDS);

  async function onPick(): Promise<void> {
    const file = input?.files?.[0];
    if (input) input.value = '';
    pending = null;
    problem = null;
    if (!file) return;
    busy = true;
    try {
      const document_ = JSON.parse(await file.text()) as unknown;
      pending = { document: document_, preview: await previewImport(document_) };
    } catch (error) {
      problem = error instanceof SyntaxError ? { message: t('opscenter.boards.import_not_json'), refusals: [] } : refusalOf(error);
    } finally {
      busy = false;
    }
  }

  async function confirm(): Promise<void> {
    if (!pending) return;
    busy = true;
    try {
      const result = await importBoard(pending.document);
      announce(t('opscenter.boards.announce_imported', { name: pending.preview.name }));
      problem = result.settings_refused.length ? { message: t('opscenter.boards.import_settings_skipped'), refusals: result.settings_refused } : null;
      pending = null;
    } catch (error) {
      problem = refusalOf(error);
    } finally {
      busy = false;
    }
  }
</script>

<button type="button" class="oc-btn oc-btn--sm" data-board-import disabled={full || busy} title={full ? t('opscenter.boards.full', { max: MAX_BOARDS }) : ''} onclick={() => input?.click()}
  >{t('opscenter.boards.import')}</button
>
<input bind:this={input} class="bt-file" type="file" accept=".json,application/json" aria-label={t('opscenter.boards.import_file')} data-board-import-file onchange={onPick} />

{#if pending}
  <div class="bt-panel" data-board-import-preview>
    <p class="oc-notice">{t('opscenter.boards.import_will_add', { name: pending.preview.name, count: pending.preview.widgets.length })}</p>
    <div class="bt-row">
      <button type="button" class="modal-btn modal-btn-secondary" onclick={() => (pending = null)}>{t('opscenter.boards.import_cancel')}</button>
      <button type="button" class="modal-btn modal-btn-confirm" data-board-import-confirm disabled={busy} onclick={confirm}>{t('opscenter.boards.import_go')}</button>
    </div>
  </div>
{/if}
{#if problem}
  <div class="bt-panel" role="alert" data-board-import-problem>
    <p class="oc-notice oc-notice--warn">{problem.message}</p>
    {#each problem.refusals as line (line)}<p class="oc-notice oc-notice--muted">{line}</p>{/each}
  </div>
{/if}

<style>
  @layer components {
  .bt-file {
    display: none;
  }

  .bt-panel {
    display: flex;
    flex: 1 0 100%;
    flex-direction: column;
    gap: var(--oc-space-1);
  }

  .bt-row {
    display: flex;
    gap: var(--oc-space-2);
  }
  }

  .bt-row :global(.modal-btn) {
    flex: 1 1 0;
    min-height: var(--oc-space-6);
    padding: 0 var(--oc-space-3);
    font-size: var(--oc-fs-body);
  }
</style>
