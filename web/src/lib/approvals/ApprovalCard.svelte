<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import ApprovalDiff from './ApprovalDiff.svelte';
  import ApprovalReview from './ApprovalReview.svelte';
  import QuestionCardFrame from './QuestionCardFrame.svelte';
  import TypedConfirm from './TypedConfirm.svelte';
  import { typedMatches } from './approval-display';
  import { askReviewKey, cardContract, cardOptionTone, foldKey, optionWords, say, type ListingRowLike } from './card-contract';
  import { follow, rememberFolded, wasFolded } from './card-fold';
  import { itemCode } from '../code-review/risk';
  import { answerDialog, approvals, decideAgentAction, noticeKey } from './approvals.svelte';
  import { sessions } from '../../opscenter/api';
  import { canApprove, diffRows, isStartupDialog, offersDismiss, optionRows, type ApprovalItem } from './approvals-model';

  let { item, onJump, strip = true, large = false, registerFoot, foldable = false, age = '' }: {
    item: ApprovalItem; onJump: (item: ApprovalItem) => void;
    registerFoot?: (foot: Snippet | null) => void;
    /* permission prompt */
    strip?: boolean;
    large?: boolean;
    foldable?: boolean;
    age?: string;
  } = $props();

  const contract = $derived(cardContract(item, { rows: (sessions.data ?? []) as ListingRowLike[] }));
  const options = $derived(optionRows(item));
  const multi = $derived(item.multi_select === true);
  const tabs = $derived(item.tabs ?? []);
  const showQuestion = $derived(item.source === 'dialog' && (contract.kind === 'question' || contract.kind === 'dialog') && !!item.question?.trim());
  const canOther = $derived(item.has_other === true && !multi);
  const diff = $derived(item.source === 'agent_action' ? diffRows(item) : []);
  let open = $state(true);
  let picked = $state<string[] | null>(null);
  let other = $state('');
  let busy = $state(false);
  let typed = $state('');
  const confirmed = $derived(typedMatches(item.confirm_text, typed));
  const notice = $derived(approvals.notices[noticeKey(item)] ?? '');
  const danger = $derived(item.display?.tone === 'danger');

  /* the bottom bar */
  const inBar = $derived(registerFoot === undefined);
  /* the bottom bar */
  const choices = $derived(inBar && item.source === 'dialog' && !multi && options.length > 0);
  /* the bottom bar */
  const hasCode = $derived(itemCode(item) !== null);

  $effect.pre(() => {
    const key = foldKey(item);
    if ((item.tabs?.length ?? 0) > 0 && item.session_id) follow(askReviewKey(item.session_id), key);
    open = !foldable || !wasFolded(key);
  });

  const ticked = $derived(picked ?? options.filter((row) => row.checked).map((row) => row.label));

  async function act(run: () => Promise<boolean>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      await run();
    } finally {
      busy = false;
    }
  }

  function toggle(label: string, on: boolean): void {
    picked = on ? [...ticked.filter((l) => l !== label), label] : ticked.filter((l) => l !== label);
  }

  $effect(() => {
    if (!registerFoot) return undefined;
    registerFoot(foot);
    return () => registerFoot(null);
  });

  function sendOther(): void {
    const text = other.trim();
    if (text) void act(() => answerDialog(item, { other: text }));
  }
</script>

{#snippet choiceButtons()}
  {#if multi && options.length}
    <button type="button" class="modal-btn modal-btn-confirm" data-ap-submit disabled={busy}
      onclick={() => act(() => answerDialog(item, { options: ticked }))}>{t('approvals.submit')}</button>
  {:else}
    {#each options as row (row.label)}
      <button type="button" class="modal-btn modal-btn-{cardOptionTone(item, row.label)}" data-ap-option disabled={busy}
        title={row.description ? `${row.label}: ${row.description}` : row.label} onclick={() => act(() => answerDialog(item, { option: row.label }))}>
        <span class="ap-opt-label">{say(optionWords(row.label))}</span>
      </button>
    {/each}
  {/if}
{/snippet}

{#snippet foot()}
  <div class="ap-foot" class:ap-foot--pinned={registerFoot !== undefined}>
    <span class="qc-chip" class:qc-chip--beast={contract.chip === 'beast'} data-qc-chip={contract.chip}>{t(`approvals.card.chip.${contract.chip}`)}</span>
    
    <div class="ap-bar" class:ap-actions={choices} data-ap-bar>
      {#if item.source === 'dialog'}
        {#if inBar}{@render choiceButtons()}{/if}
        {#if strip && canApprove(item)}
          <button type="button" class="modal-btn modal-btn-secondary" data-approval-deny disabled={busy}
            onclick={() => act(() => answerDialog(item, { plain: 'no' }))}>{t('approvals.deny')}</button>
          <button type="button" class="modal-btn modal-btn-confirm" data-approval-approve-go disabled={busy}
            onclick={() => act(() => answerDialog(item, { plain: 'yes' }))}>{t('approvals.approve')}</button>
        {/if}
        {#if hasCode}{@render review()}{/if}
        {#if offersDismiss(item)}
          <button type="button" class="modal-btn modal-btn-secondary" disabled={busy}
            onclick={() => act(() => answerDialog(item, { dismiss: true }))}>{t('approvals.dismiss')}</button>
        {/if}
      {:else if item.source === 'agent_action'}
        {#if hasCode}{@render review()}{/if}
        <button type="button" class="modal-btn modal-btn-secondary" data-approval-deny-action disabled={busy}
          onclick={() => act(() => decideAgentAction(item, false))}>{t('approvals.deny')}</button>
        <button type="button" class="modal-btn {danger ? 'modal-btn-danger' : 'modal-btn-confirm'}" data-approval-approve-action
          disabled={busy || !confirmed}
          onclick={() => act(() => decideAgentAction(item, true, item.confirm_text ? typed : undefined))}>{t('approvals.approve')}</button>
      {:else if hasCode}
        {@render review()}
      {/if}
      {#if item.source !== 'agent_action' || item.session_id}
        <button type="button" class="modal-btn modal-btn-secondary ap-jump" data-ap-jump aria-label={t('approvals.open_session')}
          title={t('approvals.open_session')} onclick={() => onJump(item)}><Icon name="external" size={14} /></button>
      {/if}
    </div>
  </div>
{/snippet}

{#snippet review()}<ApprovalReview {item} title={say(contract.headline)} />{/snippet}

{#snippet footHere()}{#if !registerFoot}{@render foot()}{/if}{/snippet}

<div class="ap-card" class:ap-card--lg={large} data-approval-card={item.id} data-source={item.source}
  data-approval-kind={contract.kind} data-startup-kind={item.source === 'startup_prompt' ? item.kind : undefined}
  data-busy={busy ? 'true' : undefined}>
  <QuestionCardFrame id={item.id} {contract} {foldable} {age} bind:open onToggle={(next) => rememberFolded(foldKey(item), !next)}
    foot={footHere}>
    {#if item.source === 'dialog'}
      {#if tabs.length}
        <div class="ap-tabs" data-approval-tabs>
          <span class="pl-label" data-approval-step>{t('approvals.question_of', { n: item.question_index ?? 1, total: tabs.length })}</span>
          <ul class="ap-tabrow" aria-label={t('approvals.question_of', { n: item.question_index ?? 1, total: tabs.length })}>
            {#each tabs as tab, i (i)}
              <li class="ap-tab" class:ap-tab--here={i + 1 === item.question_index}
                aria-current={i + 1 === item.question_index ? 'step' : undefined}>
                <span class="ap-tab__n">{String(i + 1).padStart(2, '0')}</span>
                <span class="ap-tab__title">{tab.title}</span>
                {#if tab.answered}<span class="ap-tab__mark" data-approval-step-done>{t('approvals.step_done')}</span>{/if}
              </li>
            {/each}
          </ul>
        </div>
      {/if}
      {#if showQuestion}<p class="ap-question">{item.question}</p>{/if}
      {#if !multi && options.some((row) => row.description)}
        <ul class="ap-notes" data-ap-notes>
          {#each options as row (row.label)}
            {#if row.description}<li class="ap-note"><span class="ap-note__label">{say(optionWords(row.label))}</span> {row.description}</li>{/if}
          {/each}
        </ul>
      {/if}
      {#if options.length && (multi || !inBar)}
        <div class="ap-actions ap-picks" data-startup={isStartupDialog(item) ? '' : undefined}>
          {#if multi}
            {#each options as row (row.label)}
              <Check role="checkbox" label={row.label} hint={row.description} checked={ticked.includes(row.label)} disabled={busy}
                onToggle={(next) => toggle(row.label, next)} />
            {/each}
          {/if}
          {#if !inBar}{@render choiceButtons()}{/if}
        </div>
      {/if}
      {#if canOther}
        <form class="ap-other" onsubmit={(event) => { event.preventDefault(); sendOther(); }}>
          <input class="oc-field ap-input" type="text" maxlength="2000" bind:value={other} disabled={busy}
            placeholder={t('approvals.other_placeholder')} aria-label={t('approvals.other_label')} />
          <button type="submit" class="modal-btn modal-btn-secondary" disabled={busy || !other.trim()}>{t('approvals.send')}</button>
        </form>
      {/if}
    {:else if item.source === 'agent_action'}
      {#if diff.length}<ApprovalDiff rows={diff} />{/if}
      {#if item.confirm_text}<TypedConfirm id={item.id} expected={item.confirm_text} bind:value={typed} disabled={busy} />{/if}
    {/if}
  </QuestionCardFrame>
  {#if notice}<p class="ap-card__notice" role="alert" data-approval-notice>{notice}</p>{/if}
</div>

<style>
  .ap-card { display: flex; flex-direction: column; box-shadow: inset 0 -1px 0 0 var(--pl-line-quiet); }
  .ap-card--lg :global(.qc-hl), .ap-card--lg .ap-question { font-size: var(--oc-fs-heading); line-height: 1.45; }
  .ap-card--lg :global(.qc-raw) { font-size: var(--oc-fs-status); }
    .ap-card--lg .ap-other .modal-btn, .ap-card--lg .ap-bar :global(.modal-btn), .ap-card--lg .ap-picks :global(.modal-btn) { font-size: var(--oc-fs-run-title); }
  .ap-card--lg .ap-bar :global(.modal-btn), .ap-card--lg .ap-picks :global(.modal-btn) { height: 32px; }
  .ap-card--lg .ap-bar .ap-jump { width: 32px; }
  .ap-question { margin: 0; font-size: var(--oc-fs-body); color: var(--pl-text); white-space: pre-wrap; overflow-wrap: anywhere; }
  .ap-tabs { display: flex; flex-direction: column; gap: var(--oc-space-1); }
  .ap-tabrow { display: flex; flex-wrap: wrap; gap: var(--oc-space-1) 10px; margin: 0; padding: 0; list-style: none; font-size: var(--oc-fs-hint); }
  .ap-tab { display: inline-flex; align-items: baseline; gap: 5px; padding-bottom: var(--oc-space-0-5); color: var(--pl-text); text-transform: uppercase; letter-spacing: 0.08em; }
  .ap-tab__n { font-variant-numeric: tabular-nums; opacity: 0.7; }
  .ap-tab__mark { font-size: 9px; color: var(--pl-muted); }
  .ap-tab--here { color: var(--pl-accent); box-shadow: inset 0 -1px 0 0 var(--pl-accent); }
  .ap-tab--here .ap-tab__n { opacity: 1; }
  .ap-actions :global(.modal-btn-secondary) { color: var(--pl-text); text-align: left; }
  .ap-actions :global(.modal-btn-secondary) { --_bd: var(--oc-text-dim); border-color: var(--_bd); }
  .ap-actions :global(.modal-btn-secondary:hover:not(:disabled)) { border-color: var(--oc-text-muted); }
  .ap-actions :global(.oc-check) { color: var(--pl-text); }
  .ap-actions:has(:global(.oc-check__hint)) { flex-direction: column; align-items: stretch; }
  .ap-notes { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: var(--oc-space-0-5); font-size: var(--oc-fs-label); color: var(--pl-text); }
  .ap-note { overflow-wrap: anywhere; }
  .ap-note__label { color: var(--oc-text-bright); }
  .ap-card[data-busy='true'] { opacity: 0.6; transition: opacity 0.12s ease; }
  .ap-actions { display: flex; flex-wrap: wrap; gap: var(--oc-space-1-5); }
  .ap-other { display: flex; gap: var(--oc-space-1-5); }
  .ap-input { flex: 1; min-width: 0; }
  .ap-foot { display: flex; flex-direction: column; gap: var(--oc-space-1-5); min-width: 0; }
  .ap-bar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oc-space-1-5); min-width: 0; }
  .ap-bar .ap-jump { margin-left: auto; }
  .ap-foot--pinned { flex: 1; gap: var(--oc-space-2); }
  .qc-chip {
    align-self: flex-start;
    padding: 0 var(--oc-space-1-5);
    border: var(--oc-border, 1px) solid var(--oc-line-panel);
    border-radius: var(--oc-radius-sm, 2px);
    color: var(--oc-text-dim);
    font-family: var(--font-mono);
    font-size: var(--oc-fs-micro);
    letter-spacing: 0.04em;
    line-height: 16px;
  }
  .qc-chip--beast { color: var(--oc-yellow); border-color: var(--oc-yellow); }
  .ap-other .modal-btn { padding: var(--oc-space-1) 10px; font-size: var(--oc-fs-label); }
  .ap-bar :global(.modal-btn), .ap-picks :global(.modal-btn) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    height: 26px;
    max-width: 100%;
    padding: 0 10px;
    overflow: hidden;
    font-size: var(--oc-fs-label);
    line-height: 1;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ap-bar .ap-opt-label, .ap-picks .ap-opt-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .ap-bar .ap-jump { width: 26px; padding: 0; flex: none; }
  .ap-bar :global(.modal-btn:disabled), .ap-picks :global(.modal-btn:disabled), .ap-other .modal-btn:disabled { opacity: 0.45; cursor: not-allowed; }
  @container oc-ap (max-width: 260px) {
    .ap-actions:not(.ap-bar) { flex-direction: column; align-items: stretch; }
    .ap-other { flex-direction: column; align-items: stretch; }
    .ap-other .modal-btn { align-self: flex-end; }
  }
  .ap-card__notice { margin: 0 10px var(--oc-space-2); font-size: var(--oc-fs-micro); color: var(--oc-coral); overflow-wrap: anywhere; }
</style>
