<script lang="ts">
  /* there is nothing */
  import { t } from '../i18n/index.svelte';
  import EditorControls from '../editor-controls/EditorControls.svelte';
  import IconButton from '../base/IconButton.svelte';
  import { renderMarkdown } from '../../opscenter/cells/notes/markdown';
  import { saveLight } from '../../opscenter/cells/notes/save-light';
  import type { NotesMode } from '../../opscenter/cells/notes/notes-mode';
  import { MARKDOWN_HINTS } from './hints';

  let {
    value,
    oninput,
    mode,
    onMode,
    placeholder = '',
    maxLength,
    label,
    emptyText = '',
    framed = false,
    textEl = $bindable(null),
    textProps = {},
  }: {
    value: string;
    oninput: (text: string) => void;
    mode: NotesMode;
    onMode?: (next: NotesMode) => void;
    placeholder?: string;
    maxLength?: number;
    label: string;
    emptyText?: string;
    framed?: boolean;
    textEl?: HTMLTextAreaElement | null;
    textProps?: Record<string, string>;
  } = $props();

  const KEYS = { hints: 'markdown_editor.hints', hintsTitle: 'markdown_editor.hints_title' } as const;

  const OFF_LIGHT = saveLight('no-session', 'idle', false);

  let hintsOpen = $state(false);
  let previewEl = $state<HTMLElement | null>(null);

  $effect(() => {
    const target = previewEl;
    if (!target) return;
    target.replaceChildren(renderMarkdown(value, target.ownerDocument));
  });

  function keepFocus(event: MouseEvent): void {
    event.preventDefault();
  }

  function closeOnEscape(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || !hintsOpen) return;
    event.stopPropagation();
    hintsOpen = false;
  }
</script>

<div class="oc-md-editor" data-md-editor>
  {#if onMode}
    <div class="oc-md-editor__keys">
      <EditorControls {mode} {onMode} showSave={false} light={OFF_LIGHT} onSave={() => {}} />
    </div>
  {/if}
  {#if mode === 'edit'}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="oc-notes-field" class:oc-notes-field--framed={framed} class:oc-focus-host={framed} onkeydown={closeOnEscape}>
      <textarea
        class="oc-notes-text"
        spellcheck="false"
        aria-label={label}
        placeholder={placeholder || undefined}
        maxlength={maxLength}
        bind:this={textEl}
        {value}
        oninput={(event) => oninput((event.currentTarget as HTMLTextAreaElement).value)}
        {...textProps}
      ></textarea>
      {#if hintsOpen}
        <div class="oc-md-editor__hints" role="note" aria-label={t(KEYS.hintsTitle)} data-md-hints>
          <p class="oc-md-editor__hints-title">{t(KEYS.hintsTitle)}</p>
          <dl class="oc-md-editor__hint-list">
            {#each MARKDOWN_HINTS as hint (hint.key)}
              <dt><code>{hint.syntax}</code></dt>
              <dd>{t(hint.key)}</dd>
            {/each}
          </dl>
        </div>
      {/if}
      <IconButton label={t(KEYS.hints)} variant="quiet" icon="help" iconSize={14} pressed={hintsOpen} data-md-hint-key
        onmousedown={keepFocus} onclick={() => (hintsOpen = !hintsOpen)} />
    </div>
  {:else}
    <div class="oc-notes-preview" bind:this={previewEl} data-notes-view="preview"></div>
    {#if emptyText && !value.trim()}
      <p class="oc-md-editor__empty">{emptyText}</p>
    {/if}
  {/if}
</div>

<style>
    @layer components {
        .oc-notes-field {
          position: relative;
          display: flex;
          flex: 1 1 auto;
          min-height: 0;
          container: oc-notes / size;
        }

        .oc-notes-field--framed {
          --_bd: var(--oc-control-line);
          border: 1px solid var(--_bd);
          border-radius: var(--oc-radius-sm);
        }
  

      .oc-md-editor {
        display: flex;
        flex: 1 1 auto;
        flex-direction: column;
        gap: 6px;
        min-height: 0;
        min-width: 0;
      }

      .oc-md-editor__keys {
        display: flex;
        flex: none;
        justify-content: flex-end;
      }

      .oc-notes-text {
        flex: 1 1 auto;
        min-height: 0;
        padding: var(--oc-space-1);
        border: 0;
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        line-height: 1.45;
        resize: none;
      }

      .oc-notes-text::placeholder {
        color: var(--oc-text-dim);
      }

      :global([data-md-hint-key]) {
        position: absolute;
        right: var(--oc-space-1);
        bottom: var(--oc-space-1);
        z-index: 2;
        color: var(--oc-text-dim);
      }

      :global([data-md-hint-key][aria-pressed='true']) {
        color: var(--oc-text-bright);
      }

      .oc-md-editor__hints {
        position: absolute;
        inset: var(--oc-space-1);
        z-index: 1;
        overflow-y: auto;
        padding: var(--oc-space-2);
        border-radius: var(--oc-radius-sm);
        background: var(--oc-ground-panel);
        box-shadow: inset 0 0 0 1px var(--oc-line-frame);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
      }

      .oc-md-editor__hints-title {
        margin: 0 0 var(--oc-space-1);
        color: var(--oc-text-muted);
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      .oc-md-editor__hint-list {
        display: grid;
        grid-template-columns: max-content 1fr;
        gap: 2px var(--oc-space-2);
        margin: 0;
      }

      .oc-md-editor__hint-list dt {
        color: var(--oc-text-primary);
      }

      .oc-md-editor__hint-list dd {
        margin: 0;
        color: var(--oc-text-secondary);
      }

      .oc-md-editor__hint-list code {
        font-family: var(--font-mono);
      }

      .oc-notes-preview {
        flex: 1 1 auto;
        min-height: 0;
        overflow-y: auto;
        padding-right: var(--oc-space-1);
        color: var(--oc-text-primary);
        font-size: var(--oc-fs-label);
        line-height: 1.5;
      }

      .oc-notes-preview :global(h1),
      .oc-notes-preview :global(h2),
      .oc-notes-preview :global(h3),
      .oc-notes-preview :global(h4),
      .oc-notes-preview :global(h5),
      .oc-notes-preview :global(h6) {
        margin: var(--oc-space-2) 0 var(--oc-space-1);
        color: var(--oc-text-bright);
        font-size: var(--oc-fs-label);
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }

      .oc-notes-preview :global(p),
      .oc-notes-preview :global(ul),
      .oc-notes-preview :global(ol) {
        margin: var(--oc-space-1) 0;
      }

      .oc-notes-preview :global(ul),
      .oc-notes-preview :global(ol) {
        padding-left: 18px;
      }

      .oc-notes-preview :global(code) {
        padding: 0 3px;
        border-radius: 2px;
        background: var(--oc-ground-field);
        box-shadow: inset 0 0 0 1px var(--oc-line-rule);
        font-family: var(--font-mono);
      }

      .oc-notes-preview :global(pre) {
        margin: 6px 0;
        padding: 6px var(--oc-space-2);
        overflow-x: auto;
        border-radius: 3px;
        background: var(--oc-ground-field);
        box-shadow: inset 0 0 0 1px var(--oc-line-rule);
      }

      .oc-notes-preview :global(pre) :global(code) {
        padding: 0;
        background: none;
        box-shadow: none;
      }

      .oc-notes-preview :global(blockquote) {
        margin: 6px 0;
        padding-left: var(--oc-space-2);
        border-left: 2px solid var(--oc-line-rule);
        color: var(--oc-text-secondary);
      }

      .oc-notes-preview :global(hr) {
        margin: var(--oc-space-2) 0;
        border: 0;
        border-top: 1px solid var(--oc-line-rule);
      }

      .oc-notes-preview :global(a) {
        color: var(--oc-cyan);
      }

      .oc-md-editor__empty {
        margin: 0;
        color: var(--oc-text-dim);
        font-size: var(--oc-fs-label);
      }
    }
</style>
