<script lang="ts">
  /* no longer holds there is nothing */
  import { onMount } from 'svelte';
  import { baseField } from '../task-manager-base-field';
  import { t, truncatedTip } from '../../sdk';
  import { Button } from '../../sdk/ui';
  import Icon from '../../../opscenter/ui/Icon.svelte';
  import { mdPlain } from '../task-manager-markdown';
  import { createAsk } from './ask-state.svelte';
  import { EXTRA_KEY, isDismissClick, optionForDigit, toggleChoice, type AskQuestion, type AskValue } from './ask-model';
  import AskPasteZone from './fields/AskPasteZone.svelte';
  import AskQuestionView from './AskQuestion.svelte';
  import './ask-form.css';
  import TaskManagerMarkdown from '../TaskManagerMarkdown.svelte';

  let { messageId, mode = 'panel', onClose = () => {} }: { messageId: number; mode?: 'panel' | 'inline' | 'window' | 'cell'; onClose?: () => void } = $props();

  // svelte-ignore state_referenced_locally
  const ask = createAsk(messageId);
  let root = $state<HTMLElement | null>(null);

  const name = $derived(ask.item ? (ask.item.title || ask.item.text) : '');
  const left = $derived(ask.progress.requiredLeft);
  const alone = $derived(ask.questions.some((q) => !!q.command));
  const submitLabel = $derived(
    ask.submitting ? t('cplug.huddle.ask.sending') : ask.uploading ? t('cplug.huddle.files.uploading') : left > 0 ? t('cplug.huddle.ask.required_left', { n: left }) : t('cplug.huddle.ask.submit'),
  );

  onMount(() => {
    void ask.load();
  });

  async function send(): Promise<void> {
    if (await ask.submit()) onClose();
  }

  function change(question: AskQuestion, patch: AskValue): void {
    ask.set(question.id, patch);
    if (question.type === 'single' && question.command && patch.choice && !ask.answered && ask.progress.requiredLeft === 0) void send();
  }

  async function stripClick(event: MouseEvent): Promise<void> {
    if (isDismissClick(event) && !ask.answered && (await ask.dismiss())) onClose();
  }

  function jump(from: HTMLElement | null, by: -1 | 1): void {
    const sets = [...(root?.querySelectorAll<HTMLElement>('[data-qid]') ?? [])];
    const at = sets.findIndex((s) => s.contains(from));
    const next = sets[Math.min(Math.max(at + by, 0), sets.length - 1)];
    next?.querySelector<HTMLElement>('button:not([disabled]), input, textarea, [tabindex="0"]')?.focus();
  }

  function digit(question: AskQuestion, key: string): boolean {
    const id = optionForDigit(question, key);
    if (!id || (question.type !== 'single' && question.type !== 'multi')) return false;
    change(question, question.type === 'multi' ? toggleChoice(question, ask.values[question.id], id) : { choice: id, other: '' });
    return true;
  }

  function onKeydown(event: KeyboardEvent): void {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      void send();
      return;
    }
    const target = event.target as HTMLElement;
    if (event.altKey && (event.key === 'PageDown' || event.key === 'PageUp')) {
      event.preventDefault();
      jump(target, event.key === 'PageDown' ? 1 : -1);
      return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey || target.closest('input, textarea')) return;
    const question = ask.questions.find((q) => q.id === target.closest<HTMLElement>('[data-qid]')?.dataset.qid);
    if (!question || ask.answered) return;
    const key = event.key.toLowerCase();
    let handled = false;
    if (key === 'r') { ask.take(question.id); handled = true; }
    else if (question.type === 'yes_no' && (key === 'y' || key === 'n')) { ask.set(question.id, { value: key === 'y' }); handled = true; }
    else handled = digit(question, event.key);
    if (handled) event.preventDefault();
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<section class="hdq" data-ask-form={messageId} data-ask-mode={mode} bind:this={root} aria-label={t('cplug.huddle.ask.label')} onkeydown={onKeydown}>
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="hdq-strip" data-ask-strip title={ask.answered ? undefined : t('cplug.huddle.ask.answer_hint')} onclick={stripClick}>
    <span class="hdq-label">{t('cplug.huddle.ask.label')}</span>
    {#if name}<span class="hdq-name" data-ask-name use:truncatedTip={mdPlain(name)}><TaskManagerMarkdown text={name} inline /></span>{/if}
    
    <button type="button" class="oc-ibtn oc-ibtn--bare oc-ibtn--close hdq-close" data-ask-close aria-label={t('cplug.huddle.ask.close')} title={t('cplug.huddle.ask.close')}
            onclick={(event) => { event.stopPropagation(); onClose(); }}><Icon name="close" size={14} /></button>
  </div>
  {#if ask.loading}
    <div class="hdq-hint">{t('cplug.huddle.ask.loading')}</div>
  {:else if ask.missing || !ask.read}
    <div class="hdq-hint" data-ask-missing>{t('cplug.huddle.ask.gone')}</div>
  {:else}
    <div class="hdq-questions">
      {#if ask.read.ask.context}<div class="hdq-context"><TaskManagerMarkdown text={ask.read.ask.context} /></div>{/if}
      {#each ask.questions as question, at (question.id)}
        <AskQuestionView {question} number={at + 1} value={ask.values[question.id]} answer={ask.answers[question.id]} readonly={ask.answered} busy={ask.submitting}
                         box={ask.attachments(question.id)} onChange={(patch) => change(question, patch)} onTake={() => ask.take(question.id)} />
      {/each}
      
      {#if !alone && (!ask.answered || ask.savedExtra)}
        <div class="hdq-q" data-ask-extra={messageId}>
          <label class="hdq-prompt" for={`hdq-extra-${messageId}`}>{t('cplug.huddle.ask.extra_label')}</label>
          {#if ask.answered}
            <div class="hdq-answer" data-ask-extra-answer><TaskManagerMarkdown text={ask.savedExtra} /></div>
          {:else}
            <AskPasteZone box={ask.attachments(EXTRA_KEY)} id={EXTRA_KEY}>
              <textarea class="hdq-input" use:baseField id={`hdq-extra-${messageId}`} rows="3" maxlength="4000" value={ask.extra} data-ask-extra-field
                        placeholder={t('cplug.huddle.ask.extra_placeholder')} oninput={(event) => ask.setExtra(event.currentTarget.value)}></textarea>
            </AskPasteZone>
          {/if}
        </div>
      {/if}
    </div>
    <div class="hdq-foot">
      {#if ask.answered}
        <span class="hdq-note">{t('cplug.huddle.ask.answered_note')}</span>
      {:else}
        <Button data-ask-take-all disabled={ask.canTakeAll === 0} aria-label={t('cplug.huddle.ask.take_all')} title={t('cplug.huddle.ask.take_all')}
                onclick={() => ask.takeAll()}><Icon name="check-bold" size={16} /></Button>
        {#if ask.read && !ask.answered}
          <span class="hdq-count" aria-live="polite" data-ask-progress>{ask.progress.done} / {ask.progress.total}{#if left > 0} &middot; <em>{t('cplug.huddle.ask.required_n', { n: left })}</em>{/if}</span>
        {/if}
        {#if ask.error}<span class="hdq-note hdq-note--error" role="alert" data-ask-error>{ask.error}</span>{/if}
        <span class="hdq-foot-end">
          <Button variant="confirm" data-ask-submit disabled={left > 0 || ask.submitting || ask.uploading} aria-label={submitLabel} title={submitLabel}
                  aria-busy={ask.submitting} onclick={() => void send()}><Icon name={ask.submitting ? 'hourglass' : 'send'} size={16} /></Button>
        </span>
      {/if}
    </div>
  {/if}
</section>
