<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import { Button, Field } from '../base';
  import Tabs, { panelAttrs, type TabDef } from '../../opscenter/ui/Tabs.svelte';
  import { answerAll, approvals, noticeKey } from './approvals.svelte';
  import {
    answerFor, ASK_TEXT_MAX, emptyDraft, hasOtherRow, hasPreview, hostName, isAnswered, isRemote, isUnsupportedAnswer, itemSessionName, unansweredCount,
    type ApprovalItem, type AskDraft,
  } from './approvals-model';

  let { item, onJump, registerFoot }: {
    item: ApprovalItem; onJump: (item: ApprovalItem) => void;
    registerFoot?: (foot: Snippet | null) => void;
  } = $props();

  // svelte-ignore state_referenced_locally
  const questions = item.questions ?? [];
  let drafts = $state<AskDraft[]>(questions.map(() => emptyDraft()));
  let current = $state(0);
  let busy = $state(false);
  let peek = $state<number | null>(null);

  const q = $derived(questions[current]!);
  const draft = $derived(drafts[current]!);
  const left = $derived(unansweredCount(questions, drafts));
  const unsupported = $derived(questions.some((question, i) => isUnsupportedAnswer(question, drafts[i]!)));
  const notice = $derived(approvals.notices[noticeKey(item)] ?? '');
  const previewIndex = $derived(peek ?? draft.choice ?? 0);
  const previewText = $derived(hasPreview(q) ? (q.options[previewIndex]?.preview ?? '') : '');

  function go(i: number): void {
    current = Math.max(0, Math.min(questions.length - 1, i));
    peek = null;
  }

  function pick(i: number): void {
    drafts[current] = { ...draft, choice: i, useOther: false };
  }

  function tick(i: number, on: boolean): void {
    drafts[current] = { ...draft, picks: on ? [...draft.picks, i] : draft.picks.filter((p) => p !== i) };
  }

  function typeOther(text: string): void {
    drafts[current] = { ...draft, other: text, useOther: q.multi_select ? draft.useOther : text.trim() !== '' };
  }

  const stepTabs = $derived<TabDef[]>(questions.map((question, i) => ({
    id: String(i),
    label: question.header || question.question,
    badge: isAnswered(question, drafts[i]!) ? t('approvals.step_done') : t('approvals.ask.unanswered'),
  })));
  const onLast = $derived(current === questions.length - 1);

  function onEnter(event: KeyboardEvent): void {
    if (event.key !== 'Enter' || event.isComposing || event.repeat || busy) return;
    if ((event.target as HTMLElement).closest('.ak-foot, .oc-ptab, textarea')) return;
    event.preventDefault();
    if (onLast) void submit();
    else go(current + 1);
  }

  $effect(() => {
    if (!registerFoot) return undefined;
    registerFoot(foot);
    return () => registerFoot(null);
  });

  async function submit(): Promise<void> {
    if (busy || unsupported || left === questions.length) return;
    busy = true;
    try {
      await answerAll(item, questions.map((question, i) => answerFor(question, drafts[i]!)));
    } finally {
      busy = false;
    }
  }
</script>

{#snippet foot()}
  <div class="ak-foot" class:ak-foot--pinned={registerFoot !== undefined}>
    <Button variant="quiet" size="sm" onclick={() => onJump(item)}>{t('approvals.jump')}</Button>
    <span class="ak-spacer"></span>
    {#if left > 0 && left < questions.length}<span class="ak-left" data-ask-left>{t('approvals.ask.left_out', { n: left })}</span>{/if}
    {#if questions.length > 1 && !onLast}
      <Button variant="confirm" data-ask-next disabled={busy}
        onclick={() => go(current + 1)}>{t('approvals.ask.next')}</Button>
    {/if}
    <Button variant={onLast || questions.length < 2 ? 'confirm' : 'secondary'} data-ask-submit disabled={busy || unsupported || left === questions.length}
      onclick={submit}>{t('approvals.ask.submit')}</Button>
  </div>
{/snippet}

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="ak" data-ask-form data-busy={busy ? 'true' : undefined} onkeydown={onEnter}>
  <div class="ak-meta">
    <span class="ak-name">{itemSessionName(item)}</span>
    {#if item.project}<span class="pl-label">{item.project}</span>{/if}
    {#if isRemote(item)}<span class="ak-host" data-approval-host>{hostName(item)}</span>{/if}
    <span class="pl-label" data-approval-kind>{t('approvals.kind.ask_user_question')}</span>
  </div>

  {#if questions.length > 1}
    <Tabs tabs={stepTabs} active={String(current)} onSelect={(id) => go(Number(id))} label={t('approvals.ask.questions')} idBase="ak" class="ak-tabs" />
  {/if}

  <div class="ak-panel" {...panelAttrs('ak', String(current))} data-ask-panel={current}>
    <p class="ak-question" data-ask-question>{q.question}</p>
    <p class="pl-label">{q.multi_select ? t('approvals.ask.pick_many') : t('approvals.ask.pick_one')}</p>
    <div class="ak-body" class:ak-body--preview={previewText !== ''}>
      <div class="ak-options" role={q.multi_select ? 'group' : 'radiogroup'} aria-label={q.question}>
        {#each q.options as option, i (i)}
          {#if q.multi_select}
            <Check role="checkbox" label={option.label} hint={option.description ?? ''} checked={draft.picks.includes(i)}
              disabled={busy} data-ask-option={option.label} onToggle={(next) => tick(i, next)} />
          {:else}
            <button type="button" class="oc-choice" data-base-exempt="a radio choice card with a name and a description that previews on focus; the base RadioGroup is a native radio with no preview hook, and this screen's keys and tests ride the button" role="radio" aria-checked={!draft.useOther && draft.choice === i}
              disabled={busy} data-ask-option={option.label} onclick={() => pick(i)}
              onmouseenter={() => (peek = i)} onfocus={() => (peek = i)} onmouseleave={() => (peek = null)}>
              <span class="oc-choice__top"><span class="oc-radio" aria-hidden="true"></span><span class="oc-choice__name">{option.label}</span></span>
              {#if option.description}<span class="oc-choice__desc">{option.description}</span>{/if}
            </button>
          {/if}
        {/each}
        {#if hasOtherRow(q)}
          <div class="ak-other" class:ak-other--on={q.multi_select ? draft.other.trim() !== '' : draft.useOther}>
            <label class="pl-label" for="ak-other">{t('approvals.other_label')}</label>
            <Field id="ak-other" block maxlength={ASK_TEXT_MAX} disabled={busy}
              value={draft.other} placeholder={t('approvals.other_placeholder')} data-ask-other
              oninput={(event) => typeOther((event.currentTarget as HTMLInputElement).value)} />
          </div>
        {/if}
      </div>
      {#if previewText}<pre class="ak-preview" data-ask-preview aria-label={t('approvals.ask.preview')}>{previewText}</pre>{/if}
    </div>
    {#if hasPreview(q)}
      <div class="ak-other ak-notes">
        <label class="pl-label" for="ak-notes">{t('approvals.ask.notes')}</label>
        <Field id="ak-notes" block maxlength={ASK_TEXT_MAX} disabled={busy}
          value={draft.notes} placeholder={t('approvals.ask.notes_placeholder')} data-ask-notes
          oninput={(event) => { drafts[current] = { ...draft, notes: (event.currentTarget as HTMLInputElement).value }; }} />
      </div>
    {/if}
  </div>

  {#if unsupported}<p class="ak-notice" role="alert" data-ask-unsupported>{t('approvals.ask.multi_preview_unsupported')}</p>{/if}
  {#if notice}<p class="ak-notice" role="alert" data-approval-notice>{notice}</p>{/if}

  {#if !registerFoot}{@render foot()}{/if}
</div>

<style>
  @layer components {
    .ak { display: flex; flex-direction: column; gap: var(--oc-space-3); padding: 14px; font-family: var(--font-mono); color: var(--pl-text); }
    .ak[data-busy='true'] { opacity: 0.6; transition: opacity 0.12s ease; }
    .ak-meta { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--oc-space-2); }
    .ak-name { font-size: var(--oc-fs-run-title); color: var(--pl-text); }
    .ak-host {
      padding: 0 var(--oc-space-1);
      border: var(--oc-border, 1px) solid var(--oc-cyan);
      border-radius: var(--oc-radius-sm, 2px);
      color: var(--oc-cyan);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .ak-tabs { min-width: 0; }
    .ak-panel { display: flex; flex-direction: column; gap: var(--oc-space-2); min-width: 0; }
    .ak-question { margin: 0; font-size: var(--oc-fs-heading); line-height: 1.45; color: var(--pl-text); white-space: pre-wrap; overflow-wrap: anywhere; }
    .ak-body { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--oc-space-3); }
    .ak-body--preview { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
    @media (max-width: 700px) { .ak-body--preview { grid-template-columns: minmax(0, 1fr); } }
    .ak-options { display: flex; flex-direction: column; gap: var(--oc-space-1-5); min-width: 0; }
    .ak :global(.oc-choice__name), .ak :global(.oc-check__label) { font-size: var(--oc-fs-run-title); color: var(--pl-text); white-space: normal; overflow-wrap: anywhere; }
    .ak :global(.oc-choice__desc), .ak :global(.oc-check__hint) { font-size: var(--oc-fs-body); color: var(--pl-text); opacity: 0.8; white-space: normal; overflow-wrap: anywhere; }
    .ak :global(.oc-check) { white-space: normal; padding: var(--oc-space-2) 10px; }
    .ak :global(.oc-choice) { padding: var(--oc-space-2) 10px; }
    .ak-other { display: flex; flex-direction: column; gap: var(--oc-space-1); padding-top: var(--oc-space-1); }
    .ak-preview {
      margin: 0; padding: var(--oc-space-2) 10px; max-height: 18em; overflow: auto; font-family: var(--font-mono); font-size: var(--oc-fs-body);
      color: var(--pl-text); white-space: pre-wrap; overflow-wrap: anywhere;
      box-shadow: inset 0 0 0 var(--oc-border, 1px) var(--pl-line-quiet); border-radius: var(--oc-radius-sm, 2px);
    }
    .ak-notice { margin: 0; font-size: var(--oc-fs-label, 12px); color: var(--oc-coral); overflow-wrap: anywhere; }
    .ak-foot { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oc-space-2); }
    .ak-spacer { flex: 1; }
    .ak-foot--pinned { flex: 1; }
    .ak-left { font-size: var(--oc-fs-body); color: var(--oc-yellow); }
  }
</style>
