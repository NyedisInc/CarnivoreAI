<script lang="ts">
  import { ApiError, t } from '../../sdk';
  import { killFact, retagFact, type SwarmReceipt, type ReceiptFact } from './chat-api';
  import { messageEntryId } from './chat-model';

  let { receipt, canJump, onJump, onChanged }: {
    receipt: SwarmReceipt;
    canJump: (entryId: string) => boolean;
    onJump: (entryId: string) => void;
    onChanged: () => void | Promise<void>;
  } = $props();

  let confirming = $state<string | null>(null);
  let busy = $state(false);
  let failed = $state('');

  async function change(write: () => Promise<unknown>): Promise<void> {
    if (busy) return;
    busy = true;
    failed = '';
    try {
      await write();
      confirming = null;
      await onChanged();
    } catch (error) {
      failed = error instanceof ApiError && error.message ? error.message : t('cplug.huddle.chat.receipt.failed');
    }
    busy = false;
  }

  const otherScope = (fact: ReceiptFact): 'craft' | 'project' => (fact.scope === 'craft' ? 'project' : 'craft');
</script>

<div class="hdr" data-chat-receipt={receipt.kind}>
  <span class="hdr-label">{t('cplug.huddle.chat.receipt.label')}</span>
  <p class="hdr-line">{receipt.rendered}</p>
  {#each receipt.facts.filter((f) => f.state !== 'killed') as fact (fact.id)}
    {@const msg = messageEntryId(fact.owner_message_ref)}
    <div class="hdr-fact" data-receipt-fact={fact.id}>
      <span class="hdr-title">{fact.title}</span>
      <span class="hdr-scope">{t(`cplug.huddle.chat.receipt.scope.${fact.scope}`)}</span>
      <span class="hdr-keys">
        {#if msg && canJump(msg)}
          <button type="button" class="oc-btn oc-btn--sm" onclick={() => onJump(msg)}>{t('cplug.huddle.chat.receipt.jump')}</button>
        {/if}
        <button type="button" class="oc-btn oc-btn--sm" disabled={busy} onclick={() => change(() => retagFact(fact.id, otherScope(fact)))}>
          {t(`cplug.huddle.chat.receipt.retag.${otherScope(fact)}`)}
        </button>
        {#if confirming === fact.id}
          <button type="button" class="oc-btn oc-btn--sm" disabled={busy} onclick={() => (confirming = null)}>{t('cplug.huddle.chat.receipt.keep')}</button>
          <button type="button" class="oc-btn oc-btn--sm oc-btn--danger" disabled={busy} onclick={() => change(() => killFact(fact.id))}>{t('cplug.huddle.chat.receipt.kill_confirm')}</button>
        {:else}
          <button type="button" class="oc-btn oc-btn--sm oc-btn--danger" disabled={busy} onclick={() => (confirming = fact.id)}>{t('cplug.huddle.chat.receipt.kill')}</button>
        {/if}
      </span>
    </div>
  {/each}
  {#if failed}<p class="hdr-failed" role="status">{failed}</p>{/if}
</div>

<style>
  @layer components {
    /* box-shadow */
    .hdr {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
      padding: 6px 8px;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdr-label {
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hdr-line {
      margin: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      overflow-wrap: anywhere;
    }

    .hdr-fact {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      min-width: 0;
      padding-top: 4px;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdr-title {
      min-width: 0;
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-label);
      overflow-wrap: anywhere;
    }

    .hdr-scope {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hdr-keys {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-left: auto;
    }

    .hdr-failed {
      margin: 0;
      color: var(--oc-coral);
      font-size: var(--oc-fs-micro);
    }
  }
</style>
