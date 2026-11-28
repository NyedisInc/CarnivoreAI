<script lang="ts">
  import { t } from '../../sdk';
  import { Button } from '../../sdk/ui';
  import type { TaskManagerMessage } from '../huddle-model';
  import { findItem } from '../huddle.svelte';
  import { askLead, postBody } from '../task-manager-posts';
  import TaskManagerMarkdown from '../TaskManagerMarkdown.svelte';
  import TaskManagerCommandBox from '../TaskManagerCommandBox.svelte';
  import { answerWords, answeredByComment, inlineQuestion, isDismissClick, type AskAnswer, type AskValue } from './ask-model';
  import { createAsk } from './ask-state.svelte';
  import './ask-form.css';

  let { message, compact = false }: { message: TaskManagerMessage; compact?: boolean } = $props();
  const lead = $derived(compact ? askLead(message) : '');
  // svelte-ignore state_referenced_locally
  const ask = createAsk(message.id);
  const question = $derived(inlineQuestion(message.form));
  let busy = $state(false);
  let error = $state('');
  let sent = $state('');

  const options = $derived(
    question?.type === 'yes_no'
      ? [{ id: 'yes', label: question.labels?.[0] ?? t('cplug.huddle.ask.yes'), patch: { value: true } as AskValue }, { id: 'no', label: question.labels?.[1] ?? t('cplug.huddle.ask.no'), patch: { value: false } as AskValue }]
      : (question?.options ?? []).map((o) => ({ id: o.id, label: o.label, patch: { choice: o.id, other: '' } as AskValue })),
  );
  const answered = $derived(message.answered || ask.answered);
  const stored = $derived<AskAnswer | undefined>(question ? findItem(message.item_id)?.thread.find((m) => m.answers_to === message.id)?.answers?.[question.id] : undefined);
  const byComment = $derived(answeredByComment(findItem(message.item_id)?.thread ?? [], message.id));
  const words = $derived(answerWords(stored, t) || sent || t(byComment ? 'cplug.huddle.ask.answered_by_comment' : 'cplug.huddle.ask.answered'));

  $effect(() => {
    if (ask.error) {
      error = ask.error;
      sent = '';
    }
  });

  async function act(event: MouseEvent, patch: AskValue | null, label: string): Promise<void> {
    if (busy || answered || !question) return;
    const dismiss = isDismissClick(event);
    busy = true;
    error = '';
    if (!ask.read) await ask.load();
    let ok = false;
    if (ask.missing || !ask.read) error = t('cplug.huddle.ask.gone');
    else if (dismiss) ok = await ask.dismiss();
    else {
      ask.set(question.id, patch ?? {});
      ok = await ask.submit();
    }
    if (ok) sent = dismiss ? t('cplug.huddle.ask.dismissed') : label;
    else {
      if (!error) error = ask.error || t('cplug.huddle.ask.gone');
      ask.reset();
    }
    busy = false;
  }
</script>

{#if question}
  <div class="hdq hdq-inline" data-ask-inline={message.id} data-ask-inline-state={answered ? 'answered' : busy ? 'sending' : 'open'}>
    {#if compact}{#if lead}<div class="hdq-lead" data-ask-inline-lead><TaskManagerMarkdown text={lead} inline /></div>{/if}
    {:else if message.context}<div class="hdq-context"><TaskManagerMarkdown text={postBody(message.context)} /></div>{/if}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="hdq-prompt" data-ask-inline-prompt onclick={(event) => { if (!isDismissClick(event)) return; event.stopPropagation(); void act(event, null, ''); }}><TaskManagerMarkdown text={question.prompt} inline /></div>
    {#if question.help}<div class="hdq-help"><TaskManagerMarkdown text={question.help} /></div>{/if}
    {#if question.command}<div class="hdq-command" data-ask-command={question.id}><TaskManagerCommandBox text={question.command.text} lang={question.command.lang ?? ''} /></div>{/if}
    {#if answered}
      <div class="hdq-answer" data-ask-answer={question.id}><TaskManagerMarkdown text={words} inline /></div>
    {:else}
      <div class="hdq-pills" role="group" aria-label={t('cplug.huddle.ask.inline_label')} data-ask-field={question.id}>
        {#each options as option (option.id)}
          <Button disabled={busy} data-ask-option={option.id} title={t('cplug.huddle.ask.answer_hint')}
                  onclick={(event) => void act(event, option.patch, option.label)}><TaskManagerMarkdown text={option.label} inline /></Button>
        {/each}
        {#if busy}<span class="hdq-sending" role="status" data-ask-sending={question.id}>{t('cplug.huddle.ask.sending')}</span>{/if}
      </div>
      {#if error}<div class="hdq-note hdq-note--error" role="alert" data-ask-error>{error}</div>{/if}
    {/if}
  </div>
{/if}
