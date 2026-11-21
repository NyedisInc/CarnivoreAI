<script lang="ts">
  import { t } from '../sdk';
  import { Button, ConfirmPopup, Field, IconButton } from '../sdk/ui';
  import { bookmarkDraft, endLive } from './board-api';
  import type { LiveSlot } from './board-model';

  interface Props {
    slug: string;
    live: LiveSlot;
    onchanged: () => void | Promise<void>;
  }

  let { slug, live, onchanged }: Props = $props();

  type Mode = 'idle' | 'naming' | 'ending';
  let mode = $state<Mode>('idle');
  let name = $state('');
  let busy = $state(false);
  let endKey = $state<HTMLElement | null>(null);
  let noteKey = $state<{ key: string; params: Record<string, string>; error: boolean } | null>(null);

  function toggleBookmark(): void {
    mode = mode === 'naming' ? 'idle' : 'naming';
    noteKey = null;
  }

  async function bookmark(): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      const out = await bookmarkDraft(slug, name);
      noteKey = out.unchanged
        ? { key: 'cplug.reviewboard.live.bookmark_same', params: { id: out.revision ?? '' }, error: false }
        : { key: 'cplug.reviewboard.live.bookmark_done', params: { id: out.revision ?? '' }, error: false };
      mode = 'idle';
      name = '';
      await onchanged();
    } catch {
      noteKey = { key: 'cplug.reviewboard.live.bookmark_failed', params: {}, error: true };
    } finally {
      busy = false;
    }
  }

  async function end(): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      await endLive(slug);
      mode = 'idle';
      noteKey = null;
      await onchanged();
    } catch {
      noteKey = { key: 'cplug.reviewboard.live.end_failed', params: {}, error: true };
    } finally {
      busy = false;
    }
  }
</script>

<div class="rb-views" data-live-bar>
  <span class="rb-label" data-live-label>{t('cplug.reviewboard.live.draft_label')} {live.draft.seq}</span>
  <span class="rb-tools">
    <IconButton label={t('cplug.reviewboard.live.bookmark_key')} icon="bookmark" variant="quiet" iconSize={16}
                pressed={mode === 'naming'} data-board-bookmark onclick={toggleBookmark} />
    <IconButton label={t('cplug.reviewboard.live.end_key')} icon="close" variant="danger" iconSize={16}
                pressed={mode === 'ending'} data-board-live-end bind:element={endKey} onclick={() => { mode = mode === 'ending' ? 'idle' : 'ending'; noteKey = null; }} />
  </span>
  {#if mode === 'naming'}
    <form class="rb-live-form" data-board-bookmark-form onsubmit={(e) => { e.preventDefault(); void bookmark(); }}>
      <Field maxlength={120} placeholder={t('cplug.reviewboard.live.bookmark_name')} aria-label={t('cplug.reviewboard.live.bookmark_name')}
             bind:value={name} data-board-bookmark-name />
      <Button type="submit" variant="confirm" disabled={busy} data-board-bookmark-go>{t('cplug.reviewboard.live.bookmark_go')}</Button>
      <Button onclick={() => (mode = 'idle')}>{t('cplug.reviewboard.live.cancel')}</Button>
    </form>
  {/if}
  {#if mode === 'ending'}
    <ConfirmPopup label={t('cplug.reviewboard.live.end_key')} message={t('cplug.reviewboard.live.end_confirm')} anchor={endKey} busy={busy}
                  cancelLabel={t('cplug.reviewboard.live.cancel')} confirmLabel={t('cplug.reviewboard.live.end_go')}
                  data-board-live-end-confirm confirmProps={{ 'data-board-live-end-go': '' }}
                  onConfirm={() => void end()} onCancel={() => (mode = 'idle')} />
  {/if}
  {#if noteKey}
    <span class="rb-note" class:rb-note--error={noteKey.error} role="status" data-live-note>{t(noteKey.key, noteKey.params)}</span>
  {/if}
</div>
