<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../../sdk';
  import type { NodeLooks } from '../swarm/node-look';
  import ChatAvatar from './ChatAvatar.svelte';
  import ChatMarkdown from './ChatMarkdown.svelte';
  import type { SwarmTrafficEntry } from './chat-api';
  import { trafficStatusLabel, type BurstParty } from './chat-model';

  let { entry, bare = false, head, to = null, looks = null }: {
    entry: SwarmTrafficEntry; bare?: boolean; head?: Snippet; to?: BurstParty | null; looks?: NodeLooks | null;
  } = $props();

  const toName = $derived(to?.path[to.path.length - 1]?.name || t('cplug.huddle.chat.traffic.unknown_peer'));

  const summary = $derived((entry.summary ?? '').trim());
  let open = $state(false);
  const folded = $derived(bare && !!summary && !open);

  const receipt = $derived(entry.receipt ?? null);
  const status = $derived(receipt?.status ? String(receipt.status) : '');
  const reason = $derived(receipt?.reason ? String(receipt.reason) : '');
  const failed = $derived(status === 'failed' || status === 'expired');
</script>

{#snippet receiptTag()}
  <span class="hdx-receipt" class:hdx-receipt--bad={failed} data-traffic-status={status}>
    {trafficStatusLabel(status, t)}{#if reason}<span class="hdx-reason">{reason}</span>{/if}
  </span>
{/snippet}

<div class="hdx" class:hdx--bare={bare} data-chat-traffic={entry.direction} data-traffic-id={entry.id} data-traffic-open={bare ? String(!folded) : undefined}>
  {@render head?.()}
  {#if to}
    <span class="hdx-to" data-chat-recipient={to.agentId ?? to.sessionUuid ?? ''}>
      <ChatAvatar party={to} name={toName} {looks} size={12} link /><span class="hdx-to-name">{toName}</span>
    </span>
  {/if}
  {#if !bare}
    <div class="hdx-head">
      <span class="hdx-dir">{t(entry.direction === 'out' ? 'cplug.huddle.chat.traffic.out' : 'cplug.huddle.chat.traffic.in')}</span>
      <span class="hdx-peer">{entry.peer || t('cplug.huddle.chat.traffic.unknown_peer')}</span>
      {#if status}{@render receiptTag()}{/if}
    </div>
  {/if}
  {#if folded}
    <p class="hdx-sum" data-traffic-summary>{summary}</p>
  {:else if entry.text}<div class="hdx-text"><ChatMarkdown source={entry.text} /></div>{/if}
  {#if bare && summary}
    <button type="button" class="hdx-toggle" aria-expanded={open} data-traffic-toggle onclick={() => (open = !open)}>
      {t(open ? 'cplug.huddle.chat.traffic.show_less' : 'cplug.huddle.chat.traffic.show_full')}
    </button>
  {/if}
  {#if bare && status}<div class="hdx-head">{@render receiptTag()}</div>{/if}
</div>

<style>
  @layer components {
    .hdx {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
      padding: 4px 8px 6px;
      box-shadow: inset 2px 0 0 var(--oc-line-faint), inset 0 1px 0 var(--oc-line-faint);
    }

    .hdx--bare {
      gap: 4px;
      padding: 6px 8px;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-control-radius, 2px);
      box-shadow: none;
    }
    .hdx--bare .hdx-text { color: var(--oc-text-primary); }
    .hdx--bare .hdx-receipt { margin-left: 0; }

    .hdx-head {
      display: flex;
      align-items: baseline;
      flex-wrap: wrap;
      gap: 8px;
      min-width: 0;
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .hdx-dir { color: var(--oc-text-dim); }

    .hdx-to {
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      min-width: 0;
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
    }

    .hdx-to-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .hdx-peer { color: var(--oc-text-secondary); overflow-wrap: anywhere; }

    .hdx-receipt {
      margin-left: auto;
      color: var(--oc-text-muted);
    }

    .hdx-receipt--bad { color: var(--oc-coral); }

    .hdx-reason {
      margin-left: 6px;
      text-transform: none;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }

    .hdx-sum {
      margin: 0;
      overflow: hidden;
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-label);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdx-toggle {
      align-self: flex-start;
      padding: 0;
      border: 0;
      background: none;
      color: var(--oc-text-muted);
      font: inherit;
      font-size: var(--oc-fs-micro);
      text-decoration: underline dotted;
      text-underline-offset: 3px;
      cursor: pointer;
    }

    .hdx-toggle:hover { color: var(--oc-text-primary); }

    .hdx-text {
      margin: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      overflow-wrap: anywhere;
    }
  }
</style>
