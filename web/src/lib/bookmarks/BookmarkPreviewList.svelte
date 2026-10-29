
<script lang="ts">
  import Glyph from '../Glyph.svelte';
  import { t } from '../i18n/index.svelte';
  import type { PreviewEntry } from './preview-state.svelte';

  let { entry }: { entry: PreviewEntry } = $props();
</script>

<div class="bm-preview" data-bookmark-preview data-state={entry.status}>
  {#if entry.status === 'loading'}
    <p class="bm-preview__note" role="status">{t('bookmarks.preview.loading')}</p>
  {:else if entry.status === 'error'}
    <p class="bm-preview__note bm-preview__note--error" role="status">{entry.error}</p>
  {:else if entry.parts.length === 0}
    <p class="bm-preview__note" role="status">{t('bookmarks.preview.empty')}</p>
  {:else}
    <ol class="bm-preview__list">
      {#each entry.parts as part (part.entry_uuid)}
        <li class="bm-preview__part" data-role={part.role}
          aria-label={t(part.role === 'user' ? 'bookmarks.preview.you' : 'bookmarks.preview.claude')}>
          <span class="bm-preview__role"><Glyph name={part.role === 'user' ? 'chat' : 'spark'} size={12} /></span>
          <span class="bm-preview__text">{part.text}{#if part.truncated}&hellip;{/if}</span>
        </li>
      {/each}
    </ol>
  {/if}
</div>

<style>
  @layer components {
    .bm-preview {
      padding: var(--oc-space-1) var(--oc-space-3) var(--oc-space-2) var(--oc-space-4);
      font-family: var(--font-mono);
    }

    .bm-preview__list {
      display: flex;
      flex-direction: column;
      margin: 0;
      padding: 0;
      list-style: none;
      border-left: var(--oc-border) solid var(--oc-line-panel);
    }

    .bm-preview__part {
      display: flex;
      gap: var(--oc-space-2);
      padding: var(--oc-space-1) var(--oc-space-2);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      line-height: 1.4;
    }

    .bm-preview__part:not(:first-child) {
      border-top: var(--oc-border) solid var(--oc-line-faint);
    }

    .bm-preview__part[data-role='assistant'] {
      color: var(--oc-text-primary);
    }

    .bm-preview__role {
      display: inline-flex;
      flex: none;
      padding-top: 0.15em;
      color: var(--oc-text-muted);
    }

    .bm-preview__part[data-role='assistant'] .bm-preview__role {
      color: var(--oc-violet);
    }

    .bm-preview__text {
      min-width: 0;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }

    .bm-preview__note {
      margin: 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
    }

    .bm-preview__note--error {
      color: var(--oc-coral);
    }
  }
</style>
