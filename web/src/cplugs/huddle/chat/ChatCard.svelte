<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../../sdk';
  import { setApproved, saveNote } from '../huddle.svelte';
  import type { HuddleItem } from '../huddle-model';
  import { reviewOf } from '../huddle-review';
  import ChatMarkdown from './ChatMarkdown.svelte';
  import HuddleReview from '../HuddleReview.svelte';
  import HuddleThread from '../HuddleThread.svelte';
  import SwarmDecisionKeys from '../SwarmDecisionKeys.svelte';
  import AuthorPath from './AuthorPath.svelte';
  import type { SwarmQuestion } from './chat-api';
  import { cardVariant, decisionKeys, decisionOf } from './chat-model';

  let { item, card, agentName = '', question = null, head, now = Date.now() }: {
    item: HuddleItem; card: 'done' | 'question' | 'review' | 'info'; agentName?: string; question?: SwarmQuestion | null; head?: Snippet; now?: number;
  } = $props();

  let detailsOpen = $state(false);
  const others = $derived(question?.askers?.slice(1) ?? []);

  let noting = $state(false);
  let note = $state('');
  let busy = $state(false);
  const review = $derived(reviewOf(item));
  const variant = $derived(cardVariant(item));
  const look = $derived(variant ?? card);
  const decision = $derived(variant === 'closed' ? 'closed' : decisionOf(item));
  const decidable = $derived(!decision && !variant && !decisionKeys(item) && (card === 'done' || card === 'review'));
  async function approve(withNote: boolean): Promise<void> {
    if (busy) return;
    busy = true;
    const saved = withNote && note.trim() ? await saveNote(item, note.trim()) : true;
    if (saved && (await setApproved(item, true))) {
      noting = false;
      note = '';
    }
    busy = false;
  }
</script>

<article class="hdc-card hdc-card--{look}" data-chat-card={look} data-huddle-item={item.id}>
  {@render head?.()}
  {#if variant === 'ask' && question}
    {#if question.task}<p class="hdc-ask-task" data-chat-ask-task><span class="hdc-ask-label">{t('cplug.huddle.chat.ask.task')}</span> {question.task}</p>{/if}
    <p class="hdc-ask-summary" data-chat-ask-summary>{question.summary}</p>
    <button type="button" class="hdc-ask-more" aria-expanded={detailsOpen} data-chat-ask-details-toggle
            onclick={() => (detailsOpen = !detailsOpen)}>{t(detailsOpen ? 'cplug.huddle.chat.ask.details.hide' : 'cplug.huddle.chat.ask.details.show')}</button>
    {#if detailsOpen}
      <div class="hdc-ask-details" data-chat-ask-details>
        <div class="hdc-card-text"><ChatMarkdown source={question.details} /></div>
        {#if others.length}
          <span class="hdc-ask-label">{t('cplug.huddle.chat.ask.details.askers')}</span>
          <ul class="hdc-ask-list" data-chat-ask-askers>
            {#each others as asker, i (i)}
              <li><AuthorPath path={asker.author_path?.length ? asker.author_path : [{ kind: 'agent', name: asker.name, agent_id: asker.agent_id }]} {now} /></li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  {:else}
    <header class="hdc-card-head">
      <span class="hdc-card-kind">{t(`cplug.huddle.chat.card.${look}`)}</span>
      <h3 class="hdc-card-title">{item.title || item.text}</h3>
    </header>
    {#if item.title && item.text}<div class="hdc-card-text"><ChatMarkdown source={item.text} /></div>{/if}
  {/if}
  {#if review}<HuddleReview block={review} id={item.id} />{/if}
  
  <HuddleThread {item} {agentName} noSend closed />
  <SwarmDecisionKeys {item} />
  {#if decision && !decisionKeys(item)}
    <p class="hdc-card-decision" data-chat-decision={decision}>{t(`cplug.huddle.chat.decided.${decision}`)}</p>
  {/if}
  {#if decidable}
    <div class="hdc-card-actions">
      {#if noting}
        <label class="hdc-card-label" for="hdc-note-{item.id}">{t('cplug.huddle.chat.note_label')}</label>
        <textarea id="hdc-note-{item.id}" class="oc-field hdc-card-note" rows="2" bind:value={note}
                  placeholder={t('cplug.huddle.chat.note_placeholder')}></textarea>
        <div class="hdc-card-keys">
          <button type="button" class="oc-btn oc-btn--sm" onclick={() => (noting = false)}>{t('cplug.huddle.chat.note_cancel')}</button>
          <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm" disabled={busy || !note.trim()} onclick={() => approve(true)}>{t('cplug.huddle.chat.note_save')}</button>
        </div>
      {:else}
        <div class="hdc-card-keys">
          <button type="button" class="oc-btn oc-btn--sm" disabled={busy} onclick={() => (noting = true)}>{t('cplug.huddle.chat.approve_note')}</button>
          <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm" disabled={busy} onclick={() => approve(false)}>{t('cplug.huddle.chat.approve')}</button>
        </div>
      {/if}
    </div>
  {/if}
</article>

<style>
  @layer components {
    .hdc-card {
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-width: 0;
      padding: 8px 0;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdc-card--ask { gap: var(--oc-space-3); }

    .hdc-card :global(.hdt-box) {
      max-height: none;
      margin-left: 0;
      padding: 0;
      border: 0;
      background: none;
    }

    .hdc-card :global(.hdt-msg:not(.hdt-msg--asking)) {
      border-color: var(--oc-line-faint);
      background: none;
    }

    .hdc-card :global(.hdt-msg--asking) {
      max-width: none;
      border: 0;
      border-radius: 0;
      background: none;
      padding: 8px 0 0;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdc-card :global(.hdt-msg--joe) {
      background: var(--oc-ground-raised);
      box-shadow: none;
    }

    .hdc-card :global(.hdt-msg--claude .hdt-name),
    .hdc-card :global(.hdt-msg--claude .hdt-mark) {
      color: var(--oc-text-muted);
    }

    .hdc-card-head {
      display: flex;
      align-items: baseline;
      gap: 8px;
      min-width: 0;
    }

    .hdc-card-kind {
      flex: none;
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hdc-card-title {
      margin: 0;
      min-width: 0;
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-label);
      font-weight: normal;
      overflow-wrap: anywhere;
    }

    .hdc-card-text {
      margin: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      overflow-wrap: anywhere;
    }

    .hdc-ask-task {
      margin: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      overflow-wrap: anywhere;
    }

    .hdc-ask-label {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hdc-ask-summary {
      margin: 0;
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-label);
      overflow-wrap: anywhere;
    }

    .hdc-ask-more {
      align-self: flex-start;
      padding: 0 2px;
      border: 1px solid transparent;
      border-radius: var(--oc-radius-sm, 2px);
      background: none;
      color: var(--oc-text-muted);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-decoration: underline dotted;
      text-underline-offset: 3px;
      cursor: pointer;
    }

    .hdc-ask-more:hover { color: var(--oc-text-primary); }

    .hdc-ask-details {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding-top: 8px;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdc-ask-list {
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin: 0;
      padding: 0;
      list-style: none;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-micro);
      overflow-wrap: anywhere;
    }

    .hdc-card-decision {
      margin: 0;
      padding-top: 8px;
      color: var(--oc-green-dim);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdc-card--closed .hdc-card-decision { color: var(--oc-text-muted); }

    .hdc-card-actions {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding-top: 8px;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdc-card-label {
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hdc-card-note {
      resize: vertical;
      min-height: 40px;
    }

    .hdc-card-keys {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }
  }
</style>
