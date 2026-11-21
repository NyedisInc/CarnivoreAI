<script lang="ts">
  import { onDestroy } from 'svelte';
  import { t, type ApprovalItem } from '../../sdk';
  import { ApprovalCard, Button, Field, Glyph, Icon, buttonAttrs } from '../../sdk/ui';
  import { elapsed } from '../huddle-progress';
  import type { HuddleItem } from '../huddle-model';
  import { openAuthorTerminal } from './agent-open';
  import { crumbIcon, crumbLabel, crumbLinks } from './author-path';
  import ChatCard from './ChatCard.svelte';
  import { acceptReviewCard, sendBackReviewCard, type AuthorCrumb, type SwarmWaitingItem } from './chat-api';
  import { questionOf } from './chat-model';
  import { createWaitingStore } from './waiting-store.svelte';
  import { ROLLUP_RANKS, groupsOf, kindOf, mixOf, oldestAt, reviewAsk, toneOf } from './waiting-model';

  let { agentId, rank = null, agentName = '', now = Date.now() }: { agentId: number; rank?: string | null; agentName?: string; now?: number } = $props();

  const tray = createWaitingStore(agentId);
  const stop = tray.start();
  onDestroy(stop);

  let open = $state(false);
  let noting = $state<number | null>(null);
  let note = $state('');
  let busy = $state(false);
  let failed = $state('');

  const items = $derived(tray.state.items);
  const rollup = $derived(ROLLUP_RANKS.has(rank ?? ''));
  const groups = $derived(groupsOf(items));
  const mix = $derived(mixOf(items, agentId, rollup));
  const oldest = $derived(oldestAt(items));
  const ageOf = (at: number): string => (at > 0 ? elapsed(now / 1000 - at) : '');

  async function decide(cardId: number, revision: number | undefined, back: boolean): Promise<void> {
    if (busy) return;
    busy = true;
    failed = '';
    try {
      if (back) await sendBackReviewCard(cardId, note.trim());
      else await acceptReviewCard(cardId, revision);
      noting = null;
      note = '';
      await tray.refresh();
    } catch {
      failed = t('cplug.huddle.chat.waiting.failed');
    } finally {
      busy = false;
    }
  }
</script>

{#snippet crumbs(path: AuthorCrumb[], agent: number)}
  <span class="hdc-wait-path" data-waiting-path>
    {#each path as crumb, index (index)}
      {#if index > 0}<span class="hdc-wait-sep" aria-hidden="true">&gt;</span>{/if}
      {#if index === path.length - 1 && crumbLinks(crumb)}
        <button type="button" class="hdc-wait-crumb hdc-wait-crumb--link" {...buttonAttrs('quiet', 'bare')} data-waiting-open={agent}
                onclick={() => openAuthorTerminal(crumb.agent_id ?? agent, null)}>{crumbLabel(crumb, t('cplug.huddle.chat.you'))}</button>
      {:else}
        <span class="hdc-wait-crumb">{crumbLabel(crumb, t('cplug.huddle.chat.you'))}</span>
      {/if}
    {/each}
  </span>
{/snippet}

{#snippet row(item: SwarmWaitingItem, path: AuthorCrumb[])}
  {@const kind = kindOf(item)}
  <li class="hdc-wait-row" data-waiting-item={item.id} data-waiting-kind={kind}>
    <div class="hdc-wait-head">
      <span class="hdc-wait-kind hdc-wait-kind--{toneOf(kind)}">{t(`cplug.huddle.chat.waiting.kind.${kind}`)}</span>
      {#if path.length}{@render crumbs(path, item.agent_id)}{/if}
      <span class="hdc-wait-age">{ageOf(item.at)}</span>
    </div>
    {#if item.kind === 'card' && item.entry && item.entry.kind === 'card'}
      <ChatCard item={item.entry.item as HuddleItem} card={item.entry.card} {agentName} question={questionOf(item.entry)} {now} />
    {:else if item.kind === 'approval' && item.approval}
      <ApprovalCard item={item.approval as ApprovalItem} onJump={() => openAuthorTerminal(item.agent_id, null)} />
    {:else if item.kind === 'review' && item.card}
      {@const card = item.card}
      <p class="hdc-wait-ask">{reviewAsk(card.result) || card.title}</p>
      {#if card.title}<p class="hdc-wait-sub">{card.title}</p>{/if}
      {#if noting === card.id}
        <div class="hdc-wait-note"><Field multiline rows={2} maxlength={4000} bind:value={note} aria-label={t('cplug.huddle.chat.waiting.note_label')} /></div>
      {/if}
      <div class="hdc-wait-keys">
        {#if noting === card.id}
          <Button size="sm" disabled={busy} onclick={() => { noting = null; note = ''; }}>{t('cplug.huddle.chat.waiting.cancel')}</Button>
          <Button variant="confirm" size="sm" data-waiting-send-back disabled={busy || !note.trim()}
                  onclick={() => decide(card.id, card.revision, true)}>{t('cplug.huddle.chat.waiting.send_back')}</Button>
        {:else}
          <Button variant="confirm" size="sm" data-waiting-accept disabled={busy}
                  onclick={() => decide(card.id, card.revision, false)}>{t('cplug.huddle.chat.waiting.accept')}</Button>
          <Button size="sm" disabled={busy} onclick={() => { noting = card.id; note = ''; }}>{t('cplug.huddle.chat.waiting.send_back')}</Button>
        {/if}
      </div>
    {/if}
  </li>
{/snippet}

{#if items.length > 0}
  <div class="hdc-wait" class:hdc-wait--open={open} data-waiting-tray data-waiting-count={items.length}>
    <button type="button" class="hdc-wait-strip" {...buttonAttrs('row', 'bare')} aria-expanded={open} data-waiting-toggle onclick={() => (open = !open)}>
      <span class="hdc-wait-label">{t('cplug.huddle.chat.waiting.title')}</span>
      <span class="hdc-wait-count" data-waiting-total>{items.length}</span>
      <span class="hdc-wait-mix" data-waiting-mix>
        {#if open && oldest}{t('cplug.huddle.chat.waiting.oldest', { age: ageOf(oldest) })}{:else}
          {#each mix as part, index (index)}{#if index > 0}<span aria-hidden="true">{' · '}</span>{/if}{#if part.kind}{`${part.count} `}{t(`cplug.huddle.chat.waiting.kind.${part.kind}`)}{:else if part.here}{t('cplug.huddle.chat.waiting.here', { count: part.count })}{:else}{`${part.name} ${part.count}`}{/if}{/each}
        {/if}
      </span>
      <Icon name={open ? 'chevron-down' : 'chevron-up'} size={10} />
    </button>
    {#if open}
      {#if failed}<p class="hdc-wait-failed" role="status">{failed}</p>{/if}
      <ul class="hdc-wait-list" data-waiting-list>
        {#if rollup}
          {#each groups as group (group.agentId)}
            {@const own = group.path[group.path.length - 1] ?? null}
            <li class="hdc-wait-group" data-waiting-group={group.agentId}>
              <button type="button" class="hdc-wait-group-head" {...buttonAttrs('row', 'bare')} onclick={() => openAuthorTerminal(group.agentId, null)}>
                {#each group.path as crumb, index (index)}
                  {@const mark = crumbIcon(crumb)}
                  {#if index > 0}<span class="hdc-wait-sep" aria-hidden="true">&gt;</span>{/if}
                  {#if mark.set === 'glyph'}<Glyph name={mark.name} size={11} />{:else}<Icon name={mark.name} size={11} />{/if}
                  <span class="hdc-wait-crumb">{crumbLabel(crumb, t('cplug.huddle.chat.you'))}</span>
                {/each}
                {#if !own}<span class="hdc-wait-crumb">{agentName}</span>{/if}
                <span class="hdc-wait-group-count">{group.items.length}</span>
              </button>
              <ul class="hdc-wait-list hdc-wait-list--group">
                {#each group.items as item (item.id)}{@render row(item, [])}{/each}
              </ul>
            </li>
          {/each}
        {:else}
          {#each items as item (item.id)}{@render row(item, item.agent_id === agentId ? [] : item.author_path)}{/each}
        {/if}
      </ul>
    {/if}
  </div>
{/if}

<style>
  .hdc-wait {
    display: flex;
    flex-direction: column;
    min-height: 0;
    max-height: 60%;
    background: var(--oc-ground-panel);
    box-shadow: inset 0 1px 0 var(--oc-line-hairline);
  }
  .hdc-wait--open { flex: 0 1 auto; }
  .hdc-wait-strip {
    display: flex;
    flex: none;
    align-items: center;
    gap: var(--oc-space-2);
    height: var(--oc-row-h);
    padding: 0 var(--oc-cell-pad-x);
    border: 0;
    background: var(--oc-ground-titlerow);
    color: var(--oc-text-dim);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .hdc-wait-label {
    color: var(--oc-orange);
    font-size: var(--oc-fs-micro);
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }
  .hdc-wait-count {
    padding: 0 var(--oc-space-1);
    border-radius: var(--oc-radius-sm);
    background: var(--oc-orange);
    color: var(--oc-on-accent);
    font-size: var(--oc-fs-micro);
  }
  .hdc-wait-mix { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hdc-wait-list { margin: 0; padding: 0; list-style: none; overflow-y: auto; min-height: 0; }
  .hdc-wait-list--group { overflow: visible; }
  .hdc-wait-row { padding: var(--oc-space-1-5) var(--oc-cell-pad-x); box-shadow: inset 0 1px 0 var(--oc-line-hairline); }
  .hdc-wait-head { display: flex; align-items: baseline; gap: var(--oc-space-2); min-width: 0; }
  .hdc-wait-kind { flex: none; font-size: var(--oc-fs-micro); letter-spacing: 0.12em; text-transform: uppercase; }
  .hdc-wait-kind--card { color: var(--oc-orange); }
  .hdc-wait-kind--approval { color: var(--oc-cyan); }
  .hdc-wait-kind--review { color: var(--oc-purple-light); }
  .hdc-wait-path { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hdc-wait-sep { margin: 0 var(--oc-space-1); opacity: 0.6; }
  .hdc-wait-crumb { font: inherit; }
  .hdc-wait-crumb--link { padding: 0; border: 0; background: none; color: inherit; cursor: pointer; }
  .hdc-wait-crumb--link:hover { text-decoration: underline; }
  .hdc-wait-age { flex: none; margin-left: auto; opacity: 0.7; }
  .hdc-wait-ask { margin: var(--oc-space-1) 0 0; }
  .hdc-wait-sub { margin: var(--oc-space-0-5) 0 0; opacity: 0.7; }
  .hdc-wait-note { margin-top: var(--oc-space-1-5); }
  .hdc-wait-note :global(textarea) { width: 100%; }
  .hdc-wait-keys { display: flex; gap: var(--oc-space-1-5); margin-top: var(--oc-space-1-5); }
  .hdc-wait-failed { margin: 0; padding: var(--oc-space-1) var(--oc-cell-pad-x); color: var(--oc-coral); }
  .hdc-wait-group { box-shadow: inset 0 1px 0 var(--oc-line-hairline); }
  .hdc-wait-group-head {
    display: flex;
    align-items: center;
    gap: var(--oc-space-1);
    width: 100%;
    height: var(--oc-row-h-dense);
    padding: 0 var(--oc-cell-pad-x);
    border: 0;
    background: var(--oc-ground-band);
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .hdc-wait-group-count { margin-left: auto; color: var(--oc-orange); }
</style>
