<script lang="ts">
  import { tick } from 'svelte';
  import { baseField } from '../task-manager-base-field';
  import { t } from '../../sdk';
  import { Button } from '../../sdk/ui';
  import { answerWords, hasRecommendation, isAnswered, tookRecommendation, type AskAnswer, type AskQuestion, type AskValue } from './ask-model';
  import AskYesNo from './fields/AskYesNo.svelte';
  import AskChoice from './fields/AskChoice.svelte';
  import AskRank from './fields/AskRank.svelte';
  import type { Attachments } from './ask-state.svelte';
  import AskText from './fields/AskText.svelte';
  import AskWhen from './fields/AskWhen.svelte';
  import TaskManagerMarkdown from '../TaskManagerMarkdown.svelte';
  import TaskManagerCommandBox from '../TaskManagerCommandBox.svelte';

  interface Props {
    question: AskQuestion;
    number: number;
    value: AskValue | undefined;
    answer?: AskAnswer;
    readonly?: boolean;
    busy?: boolean;
    box?: Attachments;
    onChange: (patch: AskValue) => void;
    onTake: () => void;
  }
  let { question, number, value, answer, readonly = false, busy = false, box, onChange, onTake }: Props = $props();

  let noting = $state(false);
  let noteInput = $state<HTMLInputElement | null>(null);

  async function openNote(): Promise<void> {
    noting = true;
    await tick();
    noteInput?.focus({ preventScroll: true });
    noteInput?.scrollIntoView?.({ block: 'nearest' });
  }
  const done = $derived(isAnswered(question, value));
  const tag = $derived(done ? 'answered' : question.required ? 'required' : 'optional');
  const words = $derived(answerWords(answer, t));
  const followed = $derived(readonly ? answer?.recommended ?? null : tookRecommendation(question, value));
</script>

<fieldset class="hdq-q" data-qid={question.id}>
  <legend>
    <span class="hdq-qhead">
      <span class="hdq-qnum">{number}.</span>
      <span class="hdq-prompt"><TaskManagerMarkdown text={question.prompt} inline /></span>
      <span class="hdq-tag" class:hdq-tag--done={done || (readonly && !answer?.skipped)}>{readonly ? (answer?.skipped ? t(answer.dismissed ? 'cplug.huddle.ask.dismissed' : 'cplug.huddle.ask.skipped') : t('cplug.huddle.ask.answered')) : t(`cplug.huddle.ask.tag_${tag}`)}</span>
    </span>
  </legend>
  {#if question.help || question.command}
    <div class="hdq-help">
      {#if question.help}<TaskManagerMarkdown text={question.help} />{/if}
      {#if question.command}<div class="hdq-command" data-ask-command={question.id}><TaskManagerCommandBox text={question.command.text} lang={question.command.lang ?? ''} /></div>{/if}
    </div>
  {/if}
  {#if readonly}
    {#if words}<div class="hdq-answer" data-ask-answer={question.id}><TaskManagerMarkdown text={words} inline />{#if followed === true}<span class="hdq-rec">{t('cplug.huddle.ask.rec')}</span>{/if}</div>{/if}
    {#if answer?.note}<div class="hdq-why">{t('cplug.huddle.ask.note_line', { note: answer.note })}</div>{/if}
  {:else}
    {#if question.type === 'yes_no'}<AskYesNo {question} {value} {onChange} />
    {:else if question.type === 'single' || question.type === 'multi'}<AskChoice {question} {value} {busy} {onChange} />
    {:else if question.type === 'rank'}<AskRank {question} {value} {onChange} />
    {:else}<AskText {question} {value} {box} {onChange} />{/if}
    <div class="hdq-qfoot">
      {#if hasRecommendation(question) && !done}<Button size="sm" data-ask-take={question.id} onclick={onTake}>{t('cplug.huddle.ask.take')}</Button>{/if}
      {#if noting || value?.note}
        <input bind:this={noteInput} class="hdq-input" use:baseField type="text" value={value?.note ?? ''} maxlength="500" placeholder={t('cplug.huddle.ask.note_placeholder')}
               aria-label={t('cplug.huddle.ask.note')} data-ask-note={question.id} oninput={(event) => onChange({ note: event.currentTarget.value })} />
      {:else}
        <Button size="sm" data-ask-add-note={question.id} onclick={openNote}>{t('cplug.huddle.ask.add_note')}</Button>
      {/if}
    </div>
  {/if}
</fieldset>
