<script lang="ts">
  import { providerMark, t } from '../../../cplugs/sdk';
  import { onEventFrame } from '../../../cplugs/sdk/terminal';
  import { Button } from '../../base';
  import { cardSettings } from './prefs.svelte';
  import { dismissKept, keptFor } from './keep.svelte';
  import { CARD_TTL_MS, cardOf, sideEnabled, sideOf, withCard, type Card, type CardFrame } from './model';
  import './terminal-cards.css';

  let { sessionId }: { sessionId: () => string | null } = $props();
  let cards = $state<Card[]>([]);
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const shown = $derived(!cardSettings.enabled ? [] : cardSettings.keepCards ? keptFor(sessionId()) : cards);

  function drop(id: string): void {
    clearTimeout(timers.get(id));
    timers.delete(id);
    cards = cards.filter((card) => card.id !== id);
  }

  function dismiss(card: Card): void {
    if (cardSettings.keepCards) dismissKept(card.id, card.side);
    else drop(card.id);
  }

  function holdMiddle(event: MouseEvent): void {
    if (event.button === 1) event.preventDefault();
  }

  /* middle click dismisses */
  function middleDismiss(event: MouseEvent, card: Card): void {
    if (event.button === 1) dismiss(card);
  }

  function receive(frame: CardFrame): void {
    if (!cardSettings.enabled || cardSettings.keepCards) return;
    const side = sideOf(frame, sessionId());
    if (!side || !sideEnabled(cardSettings, side)) return;
    if (cards.some((card) => card.id === frame.id)) return;
    const next = withCard(cards, cardOf(frame, side));
    for (const old of cards) if (!next.some((card) => card.id === old.id)) drop(old.id);
    cards = next;
    timers.set(frame.id, setTimeout(() => drop(frame.id), CARD_TTL_MS));
  }

  $effect(() => {
    const stop = onEventFrame<CardFrame>('crosstalk.card', receive);
    return () => {
      stop();
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
    };
  });

  function timeOf(at: number): string {
    const date = new Date(at * 1000);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
</script>

{#if shown.length}
  <div class="xtalk-layer" class:xtalk-layer--keep={cardSettings.keepCards} data-xtalk-layer>
    {#each shown as card (card.id)}
      <Button variant="row" data-xtalk-card data-message-id={card.id} data-side={card.side} aria-label={t('crosstalk.cards.dismiss')} onclick={() => dismiss(card)} onmousedown={holdMiddle} onauxclick={(event: MouseEvent) => middleDismiss(event, card)}>
        <span class="xtalk-card__head">
          <span class="xtalk-card__mark" aria-hidden="true">{@html providerMark(card.provider || null, 14).svg}</span>
          <span class="xtalk-card__direction">{t(card.side === 'sent' ? 'crosstalk.cards.to' : 'crosstalk.cards.from')}</span>
          <strong class="xtalk-card__name">@{card.peer}</strong>
          <span class="xtalk-card__meta">{card.provider}{card.model ? ` / ${card.model}` : ''}</span>
          <time class="xtalk-card__time">{timeOf(card.at)}</time>
        </span>
        <span class="xtalk-card__quote">{card.preview}</span>
      </Button>
    {/each}
  </div>
{/if}
