<script lang="ts">
  /* Escape closes it */
  import { onMount } from 'svelte';
  import { t } from '../sdk';
  import { AnchoredPopup, Icon, MarkdownEditor, type NotesMode } from '../sdk/ui';
  import { COUNTER_FROM, MAX_NOTE, readSize, writeSize } from './note-store';

  interface Props {
    value: string;
    oninput: (text: string) => void;
    onclose: () => void;
    placeholder?: string;
    panelProps?: Record<string, string>;
    textProps?: Record<string, string>;
  }

  let { value, oninput, onclose, placeholder = '', panelProps = {}, textProps = {} }: Props = $props();

  const PHONE_QUERY = '(max-width: 700px)';

  let mode = $state<NotesMode>('edit');
  let panelEl = $state<HTMLElement | null>(null);
  let textEl = $state<HTMLTextAreaElement | null>(null);
  const size = readSize();
  const count = $derived(value.length);
  const showCount = $derived(count >= COUNTER_FROM);

  function phone(): boolean {
    return typeof window.matchMedia === 'function' && window.matchMedia(PHONE_QUERY).matches;
  }

  onMount(() => {
    textEl?.focus({ preventScroll: true });
    if (typeof ResizeObserver !== 'function' || !panelEl) return;
    const target = panelEl;
    const watcher = new ResizeObserver(() => {
      if (phone() || target.offsetWidth <= 0 || target.offsetHeight <= 0) return;
      writeSize({ width: target.offsetWidth, height: target.offsetHeight });
    });
    watcher.observe(target);
    return () => watcher.disconnect();
  });
</script>


<AnchoredPopup class="rb-notes" label={t('cplug.reviewboard.notes.title')} placement="manual" outside="none" initialFocus="none"
               returnFocus={false} style="--rb-notes-w: {size.width}px; --rb-notes-h: {size.height}px" bind:element={panelEl}
               onClose={onclose} data-notes-panel {...panelProps}>
  <div class="rb-notes-inner">
    <header class="rb-notes-head">
      <span class="rb-label rb-notes-title">{t('cplug.reviewboard.notes.title')}</span>
      {#if showCount}
        <span class="rb-notes-count" data-at-cap={count >= MAX_NOTE} aria-live="polite" data-notes-count>{t('cplug.reviewboard.notes.count', { n: count, max: MAX_NOTE })}</span>
      {/if}
      <button type="button" class="rb-icon" aria-label={t('cplug.reviewboard.notes.close')} title={t('cplug.reviewboard.notes.close')}
              data-notes-close onclick={onclose}><Icon name="close" size={14} /></button>
    </header>
    <div class="rb-notes-body">
      <MarkdownEditor {value} {oninput} {mode} framed onMode={(next) => (mode = next)} {placeholder} maxLength={MAX_NOTE}
                      label={t('cplug.reviewboard.tray.note')} emptyText={t('cplug.reviewboard.notes.empty')} bind:textEl {textProps} />
    </div>
  </div>
</AnchoredPopup>
