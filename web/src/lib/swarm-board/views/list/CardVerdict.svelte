
<script lang="ts">
  import { t } from '../../../i18n/index.svelte';
  import { authFetch } from '../../../../opscenter/api/auth.svelte';
  import type { BoardData } from '../../board-data.svelte';
  import type { CardView } from '../../board-types';

  interface Props {
    card: CardView;
    data: BoardData;
  }
  let { card, data }: Props = $props();

  let note = $state('');
  let busy = $state(false);
  let said = $state<{ id: number; ok: boolean; text: string } | null>(null);
  const open = $derived(card.column === 'review');
  const noteId = $derived(`swarm-list-note-${card.id}`);

  async function verdict(path: 'done' | 'send-back', body: Record<string, unknown>, okKey: string): Promise<void> {
    const id = card.id;
    busy = true;
    try {
      await authFetch(`/swarm/cards/${id}/${path}`, { method: 'POST', body: JSON.stringify(body) });
      if (path === 'send-back') note = '';
      said = { id, ok: true, text: t(okKey, { id }) };
      await data.refresh();
    } catch (failure) {
      said = { id, ok: false, text: t('swarm.board.list.verdict.error', { error: failure instanceof Error ? failure.message : String(failure) }) };
    } finally {
      busy = false;
    }
  }
</script>

<div class="sbv" data-swarm-list-verdict data-open={open ? 'true' : 'false'}>
  <label class="sbv-label" for={noteId}>{t('swarm.board.list.note.label')}</label>
  <textarea id={noteId} class="sbv-note" rows="3" maxlength="4000" placeholder={t('swarm.board.list.note.placeholder')}
            aria-label={t('swarm.board.list.note.aria')} disabled={!open || busy} bind:value={note} data-swarm-list-note></textarea>
  <div class="sbv-keys">
    <button type="button" class="oc-btn sbv-done" disabled={!open || busy} data-swarm-list-done
            onclick={() => verdict('done', { expected_revision: card.revision }, 'swarm.board.list.verdict.done_ok')}>{t('swarm.board.list.done')}</button>
    <button type="button" class="oc-btn sbv-back" disabled={!open || busy || !note.trim()} data-swarm-list-send-back
            title={open && !note.trim() ? t('swarm.board.list.verdict.need_note') : undefined}
            onclick={() => verdict('send-back', { note: note.trim() }, 'swarm.board.list.verdict.sent_ok')}>{t('swarm.board.list.send_back')}</button>
  </div>
  {#if said && said.id === card.id}
    <p class="sbv-said" class:sbv-said--bad={!said.ok} role="status" data-swarm-list-said={said.ok ? 'ok' : 'error'}>{said.text}</p>
  {:else if !open}
    <p class="sbv-said">{t('swarm.board.list.verdict.only_review')}</p>
  {/if}
</div>

<style>
  @layer components {
    .sbv-label {
      display: block;
      margin: 26px 0 10px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbv-note {
      display: block;
      box-sizing: border-box;
      width: 100%;
      padding: 10px;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-page);
      color: var(--oc-text-bright);
      font: inherit;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-body);
      resize: none;
    }
    .sbv-note::placeholder {
      color: var(--oc-text-muted);
    }
    .sbv-note:disabled {
      opacity: 0.55;
    }
    .sbv-keys {
      display: flex;
      gap: 12px;
      margin-top: 14px;
    }
    .sbv-done {
      --_bd: var(--oc-green);
      border-color: var(--oc-green);
      background: color-mix(in srgb, var(--oc-green) 12%, transparent);
      color: var(--oc-green);
    }
    .sbv-done:hover:not(:disabled) {
      border-color: var(--oc-green-bright);
      background: color-mix(in srgb, var(--oc-green) 20%, transparent);
      color: var(--oc-green-bright);
    }
    .sbv-back {
      --_bd: var(--oc-coral);
      border-color: var(--oc-coral);
      color: var(--oc-coral);
    }
    .sbv-back:hover:not(:disabled) {
      border-color: var(--oc-coral);
      background: color-mix(in srgb, var(--oc-coral) 12%, transparent);
      color: var(--oc-coral);
    }
    .sbv-said {
      margin: 12px 0 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbv-said--bad {
      color: var(--oc-coral);
    }
  }
</style>
