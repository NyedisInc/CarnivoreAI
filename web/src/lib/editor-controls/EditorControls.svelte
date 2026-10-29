<script lang="ts">
  /* and the three */
  import { t } from '../i18n/index.svelte';
  import IconButton from '../base/IconButton.svelte';
  import type { SaveLight } from '../../opscenter/cells/notes/save-light';
  import { NOTES_MODES, type NotesMode } from '../../opscenter/cells/notes/notes-mode';

  let {
    mode = 'edit',
    onMode = () => {},
    showMode = true,
    showSave = true,
    light,
    saveState = '',
    saveDisabled = false,
    onSave,
    onClose,
    closeLabelKey = '',
    saveProps = {},
    closeProps = {},
  }: {
    mode?: NotesMode;
    onMode?: (next: NotesMode) => void;
    showMode?: boolean;
    light: SaveLight;
    showSave?: boolean;
    saveState?: string;
    saveDisabled?: boolean;
    onSave: () => void;
    onClose?: () => void;
    closeLabelKey?: string;
    saveProps?: Record<string, string>;
    closeProps?: Record<string, string>;
  } = $props();

  const KEYS = {
    group: 'opscenter.cell.notes.mode',
    edit: 'opscenter.cell.notes.edit',
    editTip: 'opscenter.cell.notes.edit_tip',
    preview: 'opscenter.cell.notes.preview',
    previewTip: 'opscenter.cell.notes.preview_tip',
  } as const;

  const ITEMS: ReadonlyArray<{ mode: NotesMode; label: string; tip: string }> = NOTES_MODES.map((m) => (
    m === 'edit' ? { mode: m, label: KEYS.edit, tip: KEYS.editTip } : { mode: m, label: KEYS.preview, tip: KEYS.previewTip }
  ));

  function keepFocus(event: MouseEvent): void {
    event.preventDefault();
  }
</script>

<div class="oc-notes-controls" data-notes-controls>
  {#if showMode}
    <div class="oc-seg oc-notes-mode" role="radiogroup" aria-label={t(KEYS.group)}>
      {#each ITEMS as item (item.mode)}
        <button
          type="button"
          role="radio"
          class="oc-seg__item"
          aria-checked={mode === item.mode}
          title={t(item.tip)}
          data-notes-mode={item.mode}
          onclick={() => onMode(item.mode)}
        >{t(item.label)}</button>
      {/each}
    </div>
  {/if}
  
  {#if showSave}
  <span class="oc-notes-disk-wrap">
    <IconButton label={saveProps['aria-label'] ?? t(light.labelKey)} variant="quiet" icon="save" iconSize={15} data-notes-save={saveState}
      data-notes-light={light.tone} aria-busy={saveState === 'saving'} disabled={saveDisabled} onmousedown={keepFocus}
      onclick={onSave} {...saveProps} />
    <span class="oc-notes-save-word" role="status">{light.wordKey ? t(light.wordKey) : ''}</span>
  </span>
  {/if}
  {#if onClose}
    <IconButton label={closeProps['aria-label'] ?? t(closeLabelKey)} variant="close" icon="close" iconSize={15} data-notes-close="" onmousedown={keepFocus}
      onclick={onClose} {...closeProps} />
  {/if}
</div>

<style>
  @layer components {
    .oc-notes-controls {
      display: flex;
      flex: 0 1 auto;
      align-items: center;
      justify-content: flex-end;
      gap: 6px;
      min-width: 0;
    }

    .oc-notes-mode {
      flex: 0 0 auto;
    }

    .oc-notes-mode :global(.oc-seg__item) {
      padding: 2px calc(var(--oc-space-2) - 1px);
      border: 1px solid transparent;
    }

    .oc-notes-disk-wrap {
      display: flex;
      flex: 0 1 auto;
      align-items: center;
      min-width: 0;
    }

    .oc-notes-controls :global(:is([data-notes-save], [data-notes-close])) {
      flex: 0 0 auto;
    }

    .oc-notes-controls :global([data-notes-light='error']) {
      color: var(--oc-coral);
    }

    .oc-notes-controls :global([data-notes-light='pending']) {
      color: var(--oc-yellow);
    }

    .oc-notes-controls :global([data-notes-light='saved']) {
      color: var(--oc-green);
    }

    .oc-notes-controls :global([data-notes-light='off']) {
      color: var(--oc-text-dim);
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

    .oc-notes-save-word:not(:empty) {
      margin-left: var(--oc-space-1);
    }

    @media (pointer: coarse) {
      .oc-notes-controls :global(:is([data-notes-save], [data-notes-close])) {
        --oc-ibtn-size: var(--oc-tap);
      }

      .oc-notes-mode :global(.oc-seg__item) {
        min-height: var(--oc-tap);
      }
    }
  }
</style>
