<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, t } from '../../sdk';
  import { AnchoredPopup, Button, IconButton, MarkdownEditor, Select, type NotesMode } from '../../sdk/ui';
  import {
    backupLabel, listMemoryFiles, readMemoryFile, restoreMemoryFile, saveMemoryFile, undoAction,
    type MemoryFile, type MemoryFileRow,
  } from './memory-api';

  interface Props {
    agentId: number;
    name: string;
    onclose: () => void;
  }

  let { agentId, name, onclose }: Props = $props();

  let files = $state<MemoryFileRow[]>([]);
  let path = $state('MEMORY.md');
  let file = $state<MemoryFile | null>(null);
  let text = $state('');
  let mode = $state<NotesMode>('edit');
  let busy = $state(false);
  let notice = $state('');
  let revertTo = $state('');

  const dirty = $derived(file !== null && text !== file.text);
  const undo = $derived(undoAction(dirty, file?.backups ?? []));
  const fileChoices = $derived(files.map((row) => ({ value: row.path, label: row.state === 'held' ? `${row.title} (${t('cplug.huddle.chat.memory.held')})` : row.title })));
  const backupChoices = $derived([
    { value: '', label: t('cplug.huddle.chat.memory.revert') },
    ...(file?.backups ?? []).map((b) => ({ value: b.id, label: backupLabel(b) })),
  ]);

  function failure(error: unknown, key: string): string {
    return error instanceof ApiError && error.message ? error.message : t(key);
  }

  function take(next: MemoryFile): void {
    file = next;
    text = next.text;
    revertTo = '';
  }

  async function run(work: () => Promise<void>, failKey: string, done = ''): Promise<void> {
    busy = true;
    notice = '';
    try {
      await work();
      notice = done;
    } catch (error) {
      notice = failure(error, failKey);
    } finally {
      busy = false;
    }
  }

  function open(next: string): Promise<void> {
    path = next;
    return run(async () => take(await readMemoryFile(agentId, next)), 'cplug.huddle.chat.memory.load_failed');
  }

  function save(): Promise<void> {
    return run(async () => {
      take(await saveMemoryFile(agentId, path, text));
      files = await listMemoryFiles(agentId);
    }, 'cplug.huddle.chat.memory.save_failed', t('cplug.huddle.chat.memory.saved'));
  }

  function restore(backupId?: string): Promise<void> {
    return run(async () => {
      take(await restoreMemoryFile(agentId, path, backupId));
      files = await listMemoryFiles(agentId);
    }, 'cplug.huddle.chat.memory.restore_failed', t('cplug.huddle.chat.memory.restored'));
  }

  function undoNow(): void {
    if (undo === 'discard' && file) text = file.text;
    else if (undo === 'restore') void restore();
  }

  onMount(() => {
    void run(async () => {
      files = await listMemoryFiles(agentId);
      take(await readMemoryFile(agentId, path));
    }, 'cplug.huddle.chat.memory.load_failed');
  });
</script>

<AnchoredPopup class="hdc-memory" label={t('cplug.huddle.chat.memory.title', { name })} placement="manual" outside="none"
               initialFocus="none" returnFocus={false} onClose={onclose} data-memory-panel>
  <div class="hdc-memory-inner">
    <header class="hdc-memory-head">
      <span class="hdc-memory-title">{t('cplug.huddle.chat.memory.title', { name })}</span>
      <IconButton label={t('cplug.huddle.chat.memory.close')} icon="close" variant="close" iconSize={14} data-memory-close onclick={onclose} />
    </header>
    <div class="hdc-memory-pick">
      <Select size="sm" aria-label={t('cplug.huddle.chat.memory.file')} value={path} options={fileChoices} disabled={busy || dirty}
              data-memory-file onchange={(event: Event) => void open((event.currentTarget as HTMLSelectElement).value)} />
    </div>
    <div class="hdc-memory-body">
      {#if file}
        <MarkdownEditor value={text} oninput={(next) => (text = next)} {mode} framed onMode={(next) => (mode = next)}
                        label={t('cplug.huddle.chat.memory.file')} emptyText={t('cplug.huddle.chat.memory.empty')}
                        textProps={{ 'data-memory-text': '' }} />
      {/if}
    </div>
    <footer class="hdc-memory-foot">
      <Button variant="secondary" size="sm" disabled={busy || undo === 'none'} data-memory-undo onclick={undoNow}>{t('cplug.huddle.chat.memory.undo')}</Button>
      <Select size="sm" aria-label={t('cplug.huddle.chat.memory.revert')} bind:value={revertTo} options={backupChoices}
              disabled={busy || dirty || (file?.backups.length ?? 0) === 0} data-memory-revert
              onchange={() => { if (revertTo) void restore(revertTo); }} />
      <span class="hdc-memory-notice" aria-live="polite" data-memory-notice>{notice}</span>
      <Button variant="confirm" size="sm" disabled={busy || !dirty} data-memory-save onclick={save}>{t('cplug.huddle.chat.memory.save')}</Button>
    </footer>
  </div>
</AnchoredPopup>

<style>
  @layer components {
    :global(.hdc-memory) {
      position: fixed;
      top: 56px;
      right: 8px;
      box-sizing: border-box;
      width: 480px;
      height: min(640px, calc(100vh - 72px));
      min-width: 300px;
      min-height: 260px;
      max-width: calc(100vw - 16px);
      max-height: calc(100vh - 64px);
      overflow: hidden;
      resize: both;
      direction: rtl;
    }

    .hdc-memory-inner { display: flex; flex-direction: column; height: 100%; direction: ltr; font-family: var(--font-mono); }

    .hdc-memory-head {
      display: flex;
      flex: none;
      align-items: center;
      gap: var(--oc-space-1);
      min-height: 28px;
      padding: 0 var(--oc-space-1) 0 var(--oc-space-2);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
    }

    .hdc-memory-title {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      color: var(--oc-pink);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-overflow: ellipsis;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .hdc-memory-pick { flex: none; padding: var(--oc-space-1) var(--oc-space-2) 0; }
    .hdc-memory-pick :global(select) { width: 100%; }
    .hdc-memory-body { display: flex; flex: 1 1 auto; flex-direction: column; min-height: 0; padding: var(--oc-space-1) var(--oc-space-2); }

    .hdc-memory-foot {
      display: flex;
      flex: none;
      align-items: center;
      gap: var(--oc-space-2);
      padding: var(--oc-space-1) var(--oc-space-2);
      box-shadow: inset 0 1px 0 0 var(--oc-line-rule);
    }

    .hdc-memory-foot :global(select) { flex: 0 1 180px; min-width: 0; }
    .hdc-memory-notice { flex: 1 1 auto; min-width: 0; overflow: hidden; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); text-overflow: ellipsis; white-space: nowrap; }

    @media (max-width: 700px) {
      :global(.hdc-memory) { top: auto; right: 0; bottom: 0; left: 0; width: auto; height: 70vh; max-width: none; resize: none; }
    }
  }
</style>
