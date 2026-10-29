<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';
  import { NOTES_MODE_KEY, isNotesMode } from './notes-mode';

  export const NOTES_WIDGET = defineWidget({
    id: 'core.notes',
    scope: 'session',
    actions: [
      { id: 'mode:edit', labelKey: 'opscenter.cell.notes.edit', kind: 'choice' },
      { id: 'mode:preview', labelKey: 'opscenter.cell.notes.preview', kind: 'choice' },
      { id: 'save', labelKey: 'opscenter.cell.notes.save_now', group: 'save' },
    ],
    state: { mode: { home: 'device', default: 'edit', valid: isNotesMode, legacyKey: NOTES_MODE_KEY } },
  });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { sessions } from '../../api';
  import { untrack } from 'svelte';
  import { dismissDrawer } from '../../../lib/right-drawer/dock.svelte';
  import { inputFocus } from '../../lib/input-focus.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { Button, State } from '../../../lib/base';
  import { acquire, release, type NoteStore } from '../../api/notes.svelte';
  import MarkdownEditor from '../../../lib/markdown-editor/MarkdownEditor.svelte';
  import NotesControls, { pressSave } from './NotesControls.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget, type WidgetHandle } from '../../widgets/shell/define-widget.svelte';
  import type { WidgetStatus } from '../../widgets/shell/widget-status';
  import type { NotesMode } from './notes-mode';
  import { useOpenFocus } from '../../shell/open-focus.svelte';

  let props: CellProps = $props();

  const KEYS = {
    noSession: 'opscenter.cell.notes.no_session',
    loading: 'opscenter.cell.notes.loading',
    noRow: 'opscenter.cell.notes.no_row',
    readFailed: 'opscenter.cell.notes.read_failed',
    conflict: 'opscenter.cell.notes.conflict',
    reload: 'opscenter.cell.notes.conflict.reload',
    overwrite: 'opscenter.cell.notes.conflict.overwrite',
    theirs: 'opscenter.cell.notes.conflict.theirs',
    emptyPreview: 'opscenter.cell.notes.empty_preview',
    label: 'opscenter.cell.notes.title',
  } as const;


  let textEl = $state<HTMLTextAreaElement | null>(null);

  const openFocus = useOpenFocus();
  $effect(() => {
    if (!textEl || !openFocus?.pending) return;
    openFocus.pending = false;
    textEl.focus({ preventScroll: true });
    const end = textEl.value.length;
    textEl.setSelectionRange(end, end);
  });

  const widget: WidgetHandle<typeof NOTES_WIDGET> = useWidget(NOTES_WIDGET, () => props, () => ({
    'mode:edit': { on: mode === 'edit', run: () => setMode('edit') },
    'mode:preview': { on: mode === 'preview', run: () => setMode('preview') },
    save: { run: () => pressSave(store, focusConflict), blocked: blockedKey ? t(blockedKey) : '' },
  }));
  const mode: NotesMode = $derived(widget.state.mode);

  const tmuxName = $derived.by((): string => {
    const id = widget.sessionId;
    if (!id) return '';
    const rows = sessions.data ?? [];
    const row = rows.find((info) => info.session?.id === id);
    return (row?.tmux_session ?? '').trim();
  });

  let store = $state<NoteStore>(acquire(''));
  const note = $derived(store.note);

  $effect(() => {
    const name = tmuxName;
    store = acquire(name);
    return () => void release(name);
  });

  $effect(() => {
    if (!props.phone) untrack(() => dismissDrawer('notes'));
  });

  const status = $derived.by((): WidgetStatus => {
    if (note.load === 'loading') return 'loading';
    if (note.load === 'failed') return 'error';
    return blockedKey ? 'none' : 'ready';
  });

  const blockedKey = $derived.by((): string => {
    if (note.load === 'no-session') return KEYS.noSession;
    if (note.load === 'loading') return KEYS.loading;
    if (note.load === 'no-note-row') return KEYS.noRow;
    if (note.load === 'failed') return KEYS.readFailed;
    return '';
  });

  const inlineDiskOnly = $derived(widget.heightState === 'compact' && !props.phone);

  let conflictEl = $state<HTMLElement | null>(null);

  function focusConflict(): void {
    conflictEl?.querySelector<HTMLButtonElement>('[data-notes-action]')?.focus();
  }

  function setMode(next: NotesMode): void {
    widget.state.mode = next;
  }

  function takeFocus(): void {
    inputFocus.claim(props.instance);
  }

  function dropFocus(event: FocusEvent): void {
    const next = event.relatedTarget;
    const body = event.currentTarget;
    if (next instanceof Node && body instanceof Node && body.contains(next)) return;
    inputFocus.release(props.instance);
    void store.save();
  }
</script>

{#snippet controls(place: 'header' | 'body' | 'corner')}
  <NotesControls {store} {mode} onMode={setMode} onConflict={focusConflict} diskOnly={place === 'body' && inlineDiskOnly} corner={place === 'corner'} />
{/snippet}

<WidgetShell {widget} {status} note={blockedKey ? t(blockedKey) : ''} {controls}>
  <div
    class="oc-notes"
    data-notes-state={note.load}
    onfocuscapture={takeFocus}
    onfocusincapture={takeFocus}
    onfocusoutcapture={dropFocus}
  >
    {#if note.conflict}
      
      <div class="oc-notes-conflict" role="group" data-notes-conflict="open" bind:this={conflictEl}>
        <State kind="warn" inline title={t(KEYS.conflict)}>
          {#snippet actions()}
            <Button size="sm" onclick={() => store.keepTheirs()} data-notes-action="theirs">{t(KEYS.reload)}</Button>
            <Button size="sm" variant="danger" onclick={() => void store.keepMine()} data-notes-action="mine">{t(KEYS.overwrite)}</Button>
          {/snippet}
        </State>
        <details class="oc-notes-theirs">
          <summary>{t(KEYS.theirs)}</summary>
          <pre>{note.conflict.body}</pre>
        </details>
      </div>
    {/if}
    <MarkdownEditor
      value={note.body}
      oninput={(text) => store.edit(text)}
      {mode}
      label={t(KEYS.label)}
      emptyText={t(KEYS.emptyPreview)}
      bind:textEl
    />
  </div>
</WidgetShell>

<style>
  .oc-notes {
    display: flex;
    flex-direction: column;
    gap: var(--oc-space-1-5);
    height: 100%;
    min-height: 0;
    overflow: hidden;
    position: relative;
    padding: var(--oc-space-1);
    box-sizing: border-box;
  }


  .oc-notes-conflict { flex: 0 0 auto; }

  .oc-notes-theirs {
    color: var(--oc-text-secondary);
    font-size: var(--oc-fs-micro);
  }

  .oc-notes-theirs pre {
    max-height: 120px;
    margin: var(--oc-space-1) 0 0;
    overflow: auto;
    font-family: var(--font-mono);
    white-space: pre-wrap;
  }
</style>
