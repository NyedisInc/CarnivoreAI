<script lang="ts">
  import { openCardOnBoard, t } from '../../sdk';
  import { eventLabel } from './chat-model';
  import { IconButton } from '../../sdk/ui';

  let { event, text, cardId = null }: { event: string; text: string; cardId?: number | null } = $props();

  const label = $derived(eventLabel(event, t));
</script>

<div class="hde" data-chat-event={event || undefined}>
  {#if cardId !== null}
    {@const id = cardId}
    <IconButton label={t('cplug.huddle.chat.card_open', { id })} icon="card" data-chat-card-open={String(id)} onclick={() => void openCardOnBoard(id)} />
  {/if}
  {#if label}<span class="hde-label">{label}</span>{/if}
  <p class="hde-text">{text}</p>
</div>

<style>
  @layer components {
    .hde {
      display: flex;
      align-items: baseline;
      gap: 8px;
      min-width: 0;
      padding: 4px 8px;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hde-label {
      flex: none;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hde-text {
      margin: 0;
      min-width: 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-hint);
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }
  }
</style>
