<script lang="ts">
  import { t } from '../../sdk';
  import { Button } from '../../sdk/ui';
  import type { TaskManagerMessage } from '../huddle-model';
  import { dismissAsk, openAsk } from './ask-host';
  import { findItem } from '../huddle.svelte';
  import { answeredByComment, drawnQuestions, isDismissClick } from './ask-model';
  import './ask-form.css';

  let { message }: { message: TaskManagerMessage } = $props();
  function press(event: MouseEvent): void {
    void (isDismissClick(event) ? dismissAsk(message.id) : openAsk(message.id));
  }
  const count = $derived(drawnQuestions(message.form ?? []).length);
  const byComment = $derived(answeredByComment(findItem(message.item_id)?.thread ?? [], message.id));
</script>

{#if message.answered}
  <div class="hdq-bubble hdq-bubble--done" data-ask-bubble={message.id} data-ask-answered="true">{byComment ? t('cplug.huddle.ask.answered_by_comment') : t('cplug.huddle.ask.bubble_answered', { n: count })}</div>
{:else}
  <div class="hdq-bubble" data-ask-bubble={message.id}>
    <span>{t('cplug.huddle.ask.bubble', { n: count })}</span>
    <Button variant="confirm" size="sm" data-ask-open={message.id} title={t('cplug.huddle.ask.answer_hint')} onclick={press}>{t('cplug.huddle.ask.answer')}</Button>
  </div>
{/if}
