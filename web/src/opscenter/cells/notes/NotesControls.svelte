<script lang="ts" module>
  import type { NoteStore } from '../../api/notes.svelte';

  export function pressSave(store: NoteStore, onConflict: () => void): void {
    if (store.note.conflict || store.note.save === 'conflict') {
      onConflict();
      return;
    }
    void store.save();
  }
</script>

<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import EditorControls from '../../../lib/editor-controls/EditorControls.svelte';
  import Icon from '../../ui/Icon.svelte';
  import { Button, IconButton } from '../../../lib/base';
  import { saveLight } from './save-light';
  import type { NotesMode } from './notes-mode';

  let { store, mode, onMode, onConflict, diskOnly = false, corner = false }: {
    store: NoteStore;
    mode: NotesMode;
    onMode: (next: NotesMode) => void;
    onConflict: () => void;
    diskOnly?: boolean;
    corner?: boolean;
  } = $props();

  const note = $derived(store.note);

  const KEYS = { edit: 'opscenter.cell.notes.edit', preview: 'opscenter.cell.notes.preview' } as const;

  const light = $derived(saveLight(note.load, note.save, note.dirty));

  function pressDisk(): void {
    pressSave(store, onConflict);
  }

  function keepFocus(event: MouseEvent): void {
    event.preventDefault();
  }
</script>

{#if corner}
  <div class="oc-notes-controls oc-notes-controls--corner" data-notes-controls>
    {#if light.tone === 'error'}
      <Button variant="quiet" size="sm" role="status" data-notes-light="error" aria-label={t(light.labelKey)}
        onmousedown={keepFocus} onclick={pressDisk}><span class="oc-notes-save-word">{t(light.wordKey)}</span></Button>
    {/if}
    <IconButton label={t(mode === 'edit' ? KEYS.preview : KEYS.edit)} variant="quiet" data-notes-toggle={mode} onmousedown={keepFocus}
      onclick={() => onMode(mode === 'edit' ? 'preview' : 'edit')}><Icon name={mode === 'edit' ? 'eye' : 'pencil'} size={15} /></IconButton>
  </div>
{:else}
  <EditorControls {mode} {onMode} showMode={!diskOnly} {light} saveState={note.save}
    saveDisabled={light.tone === 'off'} onSave={pressDisk} />
{/if}

<style>
  @layer components {
    .oc-notes-controls--corner {
      position: absolute;
      top: var(--oc-space-1);
      right: var(--oc-space-1);
      z-index: 1;
      display: flex;
      align-items: center;
      gap: var(--oc-space-1-5);
    }

    .oc-notes-save-word {
      min-width: 0;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: var(--oc-coral);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
    }
  }
</style>
