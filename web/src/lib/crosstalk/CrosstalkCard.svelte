<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { providerMark } from '../sessions/agent-marks';
  import { openSession } from '../../opscenter/api/host';
  import { sessions } from '../../opscenter/api/sessions.svelte';
  import type { CrosstalkMessage } from './message';
  import './cards.css';

  let { message, sessionId }: { message: CrosstalkMessage; sessionId: string } = $props();
  let expanded = $state(false);
  const sent = $derived(message.sender_id === sessionId || message.sender_uuid === sessionId);
  const peer = $derived(sent ? (message.receiver_name || message.receiver_id) : message.sender_name);
  const provider = $derived(sent ? message.receiver_provider : message.sender_provider);
  const model = $derived(sent ? message.receiver_model : message.sender_model);
  const mark = $derived(providerMark(provider || null, 14));
  const sender = $derived(!sent ? (sessions.data ?? []).find((row) => row.session.id === message.sender_id) : null);
  const date = $derived(new Date(message.created_at * 1000));
  const time = $derived(Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));

  function toggleFromCard(event: MouseEvent): void {
    const selection = window.getSelection();
    const card = event.currentTarget as HTMLElement;
    if (selection?.toString() && card.contains(selection.anchorNode) && card.contains(selection.focusNode)) return;
    expanded = !expanded;
  }

  function openSender(event: MouseEvent): void {
    event.stopPropagation();
    if (sender) openSession(sender.session.id, sender.tmux_session);
  }
</script>


<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<article class="crosstalk-card" data-message-id={message.id} data-direction={sent ? 'outbound' : 'inbound'} onclick={toggleFromCard}>
  <header class="crosstalk-card__head">
    <span class="crosstalk-card__mark" aria-hidden="true">{@html mark.svg}</span>
    <span class="crosstalk-card__direction">{t(sent ? 'crosstalk.sent' : 'crosstalk.received')}</span>
    {#if sender}
      <button class="crosstalk-card__name crosstalk-card__sender" type="button" onclick={openSender}>@{peer}</button>
    {:else}
      <strong class="crosstalk-card__name">@{peer}</strong>
    {/if}
    <span class="crosstalk-card__meta">{provider}{model ? ` / ${model}` : ''}</span>
    <time class="crosstalk-card__time" datetime={date.toISOString()}>{time}</time>
  </header>
  <blockquote class:crosstalk-card__quote--expanded={expanded} class="crosstalk-card__quote">{message.text}</blockquote>
  <button class="crosstalk-card__toggle" type="button" aria-expanded={expanded} onclick={(event) => { event.stopPropagation(); expanded = !expanded; }}>
    {t(expanded ? 'crosstalk.show_less' : 'crosstalk.show_more')}
  </button>
</article>
