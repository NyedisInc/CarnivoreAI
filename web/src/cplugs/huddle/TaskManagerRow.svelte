<script lang="ts">
  import { getContext, untrack } from 'svelte';
  import { baseField } from './task-manager-base-field';
  import { Icon } from '../sdk/ui';
  import { DETAIL_SLOT, type DetailSlot } from './task-manager-detail-slot';
  import { BODY_OPTIONS, DEFAULT_BODY_OPTIONS, type BodyOptions } from './task-manager-body-options';
  import { taskRowMenu } from './task-manager-row-menu';
  import { Button, Check } from '../sdk/ui';
  import { tickItem } from './task-manager-tick-confirm.svelte';
  import { forwardMenuKey, menuRightClick, providerMark, t, truncatedTip } from '../sdk';
  import { huddle, loadThread, saveNote, toggleRow } from './huddle.svelte';
  import { askDelete } from './task-manager-tick-confirm.svelte';
  import { threadCount } from './task-manager-optimistic';
  import { isFocused } from './task-manager-focus.svelte';
  import { hasOpenQuestion, isApproved, isInfo, stateKey, type HuddleItem } from './huddle-model';
  import { STATUS_COLOR, STATUS_ICON, statusIconColor, statusKey, statusOf } from './huddle-status';
  import { SIGNAL_LABEL, stripeColor, stripeSignal } from './task-manager-lights';
  import { markerKey, markerOf } from './task-manager-markers';
  import TaskManagerMarker from './TaskManagerMarker.svelte';
  import HuddleThread from './HuddleThread.svelte';
  import TaskManagerProgress from './TaskManagerProgress.svelte';
  import TaskManagerSteps from './TaskManagerSteps.svelte';
  import { stepsOfItem } from './task-manager-steps.svelte';
  import SwarmDecisionKeys from './SwarmDecisionKeys.svelte';
  import { decisionKeys } from './chat/chat-model';
  import HuddleReview from './HuddleReview.svelte';
  import TaskManagerActionTag from './TaskManagerActionTag.svelte';
  import { actionOf, isStatusEcho, reviewAnswerOf, reviewOf } from './huddle-review';
  import TaskManagerRowPeek from './TaskManagerRowPeek.svelte';
  import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';
  import { mdPlain } from './task-manager-markdown';
  import { POST_KINDS, POST_KIND_LIST, unreadCount } from './task-manager-posts';
  import HuddleReply from './HuddleReply.svelte';
  import TaskManagerTitleEdit from './TaskManagerTitleEdit.svelte';
  import TaskManagerForkedFrom from './TaskManagerForkedFrom.svelte';
  import TaskManagerFromInbox from './TaskManagerFromInbox.svelte';
  import { shownAuthor } from './task-manager-author';
  import TaskManagerFromProject from './TaskManagerFromProject.svelte';
  import TaskManagerTagged from './TaskManagerTagged.svelte';
  import TaskManagerWait from './TaskManagerWait.svelte';
  import TaskManagerGithubIssue from './TaskManagerGithubIssue.svelte';
  import TaskManagerSchedule from './TaskManagerSchedule.svelte';
  import { dueLabel, dueState, repeatLabel } from './task-manager-schedule';
  import { waitChip } from './task-manager-wait';
  import { focusOpens, rowParts, rowTitle, wrapperParts } from './huddle-density';
  import { TaskWrapper, type TaskState } from '../sdk/ui';
  import { openScheduleEditor } from './task-manager-schedule-editor.svelte';
  import CrosstalkTrail from './CrosstalkTrail.svelte';
  import { taskManagerPrefs } from './task-manager-prefs.svelte';

  let { item, index, count, lines = 1, dragging = false, onGripDown, onStep }: {
    item: HuddleItem;
    index: number;
    count: number;
    lines?: 1 | 2;
    dragging?: boolean;
    onGripDown?: (event: PointerEvent, index: number) => void;
    onStep?: (index: number, delta: number) => void;
  } = $props();

  const options: Readonly<BodyOptions> = getContext<BodyOptions | undefined>(BODY_OPTIONS) ?? DEFAULT_BODY_OPTIONS;
  const wrapped = options.taskWrapper;
  const asking = $derived(hasOpenQuestion(item));
  const review = $derived(reviewOf(item));
  const reviewAnswer = $derived(review ? reviewAnswerOf(item) : null);
  const needsAction = $derived(item.needs_you ? actionOf(item.needs_action) : null);
  const density = $derived(taskManagerPrefs.density);
  const taskState = $derived<TaskState>(options.taskState === 'compact' || options.taskState === undefined ? (huddle.openId === item.id ? 'opened' : 'compact') : options.taskState);
  const parts = $derived(wrapped ? wrapperParts(taskState, item) : rowParts(density, item));
  const title = $derived(rowTitle(item));
  const plainText = $derived(mdPlain(item.text));
  const due = $derived(dueState(item));
  const waiting = $derived(waitChip(item, new Date(), { t, due: { today: t('cplug.huddle.schedule.today'), tomorrow: t('cplug.huddle.schedule.tomorrow') } }));
  const dueText = $derived(item.start_trigger ? dueLabel(item.start_trigger.fire_at, new Date(), { today: t('cplug.huddle.schedule.today'), tomorrow: t('cplug.huddle.schedule.tomorrow') }) : '');
  const clip = $derived((wrapped ? taskState === 'compact' : density === 'compact') ? 1 : (wrapped ? taskState === 'detailed' : density === 'full') ? 0 : lines);
  const open = $derived(wrapped ? taskState !== 'compact' : huddle.openId === item.id);
  const toggleProps = $derived({
    'aria-label': open ? item.text : undefined,
    'data-task-manager-toggle': item.id,
  });
  const focused = $derived(isFocused(item.id));
  const stateLabel = $derived(t(stateKey(item.state)));
  const status = $derived(statusOf(item));
  const DetailTop = getContext<DetailSlot | undefined>(DETAIL_SLOT);
  const signal = $derived(stripeSignal(item));
  const statusLabel = $derived(t(statusKey(status)));
  const marker = $derived(markerOf(item));
  const stripe = $derived(stripeColor(STATUS_COLOR[status], signal));
  const stripeLabel = $derived([statusLabel, signal ? t(SIGNAL_LABEL[signal]) : ''].filter(Boolean).join(', '));
  const markIcon = $derived(STATUS_ICON[status]);
  const ico = $derived(options.drawerIcons ? { main: 14, small: 12, stroke: 2 } : { main: 12, small: 11, stroke: undefined });
  const markColor = $derived(statusIconColor(status));
  const markLabel = $derived(statusLabel);
  const mark = $derived(shownAuthor(item) === 'claude' ? providerMark('claude', ico.main) : null);
  function peek(): void {
    if (options.taskState === 'compact' || options.taskState === undefined) huddle.openId = huddle.openId === item.id ? null : item.id;
  }
  let row = $state<HTMLElement | null>(null);
  $effect(() => {
    if (!wrapped || !row || huddle.openId !== item.id || taskState !== 'opened' || (options.taskState !== 'compact' && options.taskState !== undefined)) return;
    const away = (event: PointerEvent): void => { if (!row?.contains(event.target as Node) && huddle.openId === item.id) huddle.openId = null; };
    document.addEventListener('pointerdown', away, true);
    return () => document.removeEventListener('pointerdown', away, true);
  });
  let editingNote = $state(false);
  let noteDraft = $state('');
  let decided = false;
  $effect(() => {
    const now = asking;
    const ready = taskManagerPrefs.loaded;
    const compact = focusOpens(taskManagerPrefs.density);
    if (!now) {
      decided = false;
      return;
    }
    if (!ready || decided) return;
    decided = true;
    if (compact && !wrapped) huddle.openId = untrack(() => item.id);
  });

  $effect(() => {
    if (open && item.thread_slim) void loadThread(untrack(() => item.id));
  });

  function editNote(): void {
    noteDraft = item.note;
    editingNote = true;
  }

  async function commitNote(): Promise<void> {
    if (await saveNote(item, noteDraft)) editingNote = false;
  }

  function onGripKey(event: KeyboardEvent): void {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
    event.preventDefault();
    const delta = event.key === 'ArrowUp' ? -1 : 1;
    if (index + delta >= 0 && index + delta < count) onStep?.(index, delta);
  }
</script>

{#snippet leadChrome()}
  <span class="tkm-state" aria-hidden="true" title={stripeLabel} data-task-manager-status={status} data-task-manager-signal={signal ?? undefined}></span>
  
  {#if marker}<span class="tkm-marker" title={t(markerKey(marker))} data-task-manager-row-marker={item.id}><TaskManagerMarker id={marker} size={8} label={t(markerKey(marker))} /></span>{/if}
  {#if onGripDown}
    <button type="button" class="tkm-grip" data-task-manager-grip={item.id}
            aria-label={t('cplug.huddle.row.grip', { text: plainText })} title={t('cplug.huddle.row.grip', { text: plainText })}
            onpointerdown={(event) => onGripDown(event, index)} onkeydown={onGripKey}><Icon name="grip" size={ico.main} strokeWidth={ico.stroke} /></button>
  {:else}
    <span class="tkm-grip-gap" aria-hidden="true"></span>
  {/if}
  <Check label="" bare checked={isApproved(item.state)} ariaLabel={t('cplug.huddle.row.approve', { text: item.text })}
         data-task-manager-check={String(item.id)} onToggle={(next) => void tickItem(item, next)} />
{/snippet}

{#snippet headLine()}
    <span class="tkm-status" role="img" aria-label={markLabel} title={markLabel} style:--_icon={markColor}
          data-task-manager-status-icon={status}><Icon name={markIcon} size={ico.main} strokeWidth={ico.stroke ?? 1.75} /></span>
    <span class="hdr-line">
      {#if signal}
        <span class="oc-visually-hidden" data-task-manager-signal-label={item.id}>{t(SIGNAL_LABEL[signal])}</span>
      {/if}
      {#if focused}<span class="oc-visually-hidden" data-task-manager-focus-label>{t('cplug.huddle.focus.label')}</span>{/if}
      {#if !parts.extras}
        
      {:else if mark}
        <span class="tkm-by" role="img" aria-label={t('cplug.huddle.row.by_claude_title')} title={t('cplug.huddle.row.by_claude_title')}
              data-task-manager-by-claude={mark.key}>{@html mark.svg}</span>
      {:else}
        <span class="tkm-by" role="img" aria-label={t('cplug.huddle.row.by_joe_title')} title={t('cplug.huddle.row.by_joe_title')}
              data-task-manager-by-joe><Icon name="person-bust" size={ico.main} strokeWidth={ico.stroke} /></span>
      {/if}
      {#if open && !wrapped}
        <span class="tkm-tag" data-task-manager-state={item.state}>{stateLabel}</span>
      {:else}
        <span class="oc-visually-hidden" data-task-manager-state={item.state}>{stateLabel}</span>
      {/if}
      <span class="oc-visually-hidden" data-task-manager-status-label>{statusLabel}</span>
      {#if needsAction && !(wrapped && isStatusEcho(needsAction))}<TaskManagerActionTag action={needsAction} id={item.id} />{/if}
      {#if asking && !wrapped}<span class="tkm-asking">{t('cplug.huddle.row.asking')}</span>{/if}
      
      {#if !open || wrapped}<span class="tkm-text" class:tkm-text--clip={clip === 1} class:tkm-text--clip2={clip === 2} data-fit-clip={clip > 0 ? "" : undefined} data-task-manager-row-title={item.id} use:truncatedTip={mdPlain(title)}><TaskManagerMarkdown text={title} inline /></span>
      {:else if item.title}<span class="tkm-text tkm-text--clip" data-fit-clip data-task-manager-row-title={item.id} use:truncatedTip={mdPlain(item.title ?? "")}><TaskManagerMarkdown text={item.title} inline /></span>{/if}
      {#if !open && parts.posts === 'count'}
        {#each POST_KIND_LIST as kind (kind)}
          {@const n = unreadCount(item, kind)}
          {#if n > 0}<span class="tkm-posts-n" style:--_post={POST_KINDS[kind].color} title={t(POST_KINDS[kind].countKey, { count: n })}
                data-task-manager-posts-count={item.id} data-task-manager-post-kind={kind}><Icon name={POST_KINDS[kind].icon} size={ico.small} strokeWidth={ico.stroke} />{n}</span>{/if}
        {/each}
      {/if}
      {#if due && item.start_trigger}
        {@const repeat = item.start_trigger.repeat}
        
        <span class="tkm-when">
        <span class="tkm-due" data-task-manager-due={item.id} data-due-state={due} data-task-manager-due-repeat={repeat ? item.id : undefined}
              title={due === 'failed' ? t('cplug.huddle.schedule.failed', { error: item.start_trigger.last_error ?? '' }) : repeat ? t(due === 'paused' ? 'cplug.huddle.schedule.repeat_paused_title' : 'cplug.huddle.schedule.repeat_row_title', { repeat: repeatLabel(repeat, t), time: dueText }) : t(due === 'fired' ? 'cplug.huddle.schedule.sent_at' : 'cplug.huddle.schedule.row_title', { time: dueText })}><Icon name={repeat ? 'cycle' : 'clock'} size={ico.small} strokeWidth={ico.stroke} />{due === 'paused' ? t('cplug.huddle.schedule.paused') : dueText}</span>
        
        {#if wrapped && !isApproved(item.state)}
          <Button size="sm" data-task-manager-schedule-edit-row={item.id} aria-label={t('cplug.huddle.schedule.edit')}
                  onclick={(event: MouseEvent) => { event.stopPropagation(); openScheduleEditor(item.list, item); }}>{t('cplug.huddle.schedule.edit_row')}</Button>
        {/if}
        </span>
      {/if}
      {#if !open && parts.extras && waiting}
        <span class="tkm-due" data-task-manager-wait-chip={item.id} data-wait-overdue={waiting.overdue ? 'true' : undefined} data-wait-hold={waiting.hold ? 'true' : undefined}
              title={t(waiting.hold ? 'cplug.huddle.wait.forks_tip' : 'cplug.huddle.wait.tip')}>{waiting.label}</span>
      {/if}
      {#if !open && parts.extras && threadCount(item)}<span class="tkm-count" title={t('cplug.huddle.row.thread', { count: threadCount(item) })}><Icon name="chat" size={ico.small} strokeWidth={ico.stroke} />{threadCount(item)}</span>{/if}
    </span>
{/snippet}

{#snippet keysChrome()}
    <span class="hdr-keys" data-task-manager-keys={item.id}>
      <button type="button" class="oc-ibtn oc-ibtn--bare tkm-key" data-task-manager-note-open={item.id}
              aria-label={t(item.note ? 'cplug.huddle.row.note_edit' : 'cplug.huddle.row.note_add')}
              title={t(item.note ? 'cplug.huddle.row.note_edit' : 'cplug.huddle.row.note_add')} onclick={editNote}><Icon name="docs" size={ico.main} strokeWidth={ico.stroke} /></button>
      <button type="button" class="oc-ibtn oc-ibtn--bare tkm-key tkm-remove" data-task-manager-delete={item.id}
              aria-label={t('cplug.huddle.row.delete', { text: plainText })}
              onclick={() => askDelete(item)}><Icon name="close" size={ico.small} strokeWidth={ico.stroke} /></button>
    </span>
{/snippet}

{#snippet detailBody()}
    <div class="tkm-detail tkm-lead-host" data-task-manager-detail={item.id}>
      {#if DetailTop}<DetailTop {item} detailed={taskState === 'detailed'} />{:else if wrapped && !decisionKeys(item)}<HuddleReply {item} />{/if}
      {#if options.subtasks}<TaskManagerForkedFrom {item} />{/if}
      <TaskManagerFromProject {item} />
      {#if !options.tabbedDetail}<TaskManagerTagged {item} />{/if}
      {#if !options.tabbedDetail}<TaskManagerWait {item} />{/if}
      {#if options.issueLink}<TaskManagerGithubIssue {item} />{/if}
      {#if !options.tabbedDetail}<TaskManagerFromInbox {item} />{/if}
      {#if !options.tabbedDetail}<TaskManagerProgress id={item.id} full />{/if}
      {#if options.subtasks}<TaskManagerSteps entry={stepsOfItem(item.list, item.id)} open />{/if}
      <TaskManagerTitleEdit {item} />
      {#if options.scheduleBlocks && !isApproved(item.state)}<TaskManagerSchedule {item} />{/if}
      {#if item.note && !editingNote && !options.tabbedDetail}
        <p class="tkm-note" data-task-manager-note={item.id}><span class="hdr-label">{t('cplug.huddle.row.note')}</span>{item.note}</p>
      {/if}
      {#if editingNote}
        <div class="tkm-note tkm-note-edit">
          <span class="hdr-label">{t('cplug.huddle.row.note')}</span>
          <textarea class="oc-field tkm-note-input" use:baseField rows="2" bind:value={noteDraft} placeholder={t('cplug.huddle.row.note_placeholder')}
                    aria-label={t('cplug.huddle.row.note_placeholder')} data-task-manager-note-input={item.id}></textarea>
          <div class="tkm-note-actions">
            <button type="button" class="oc-btn oc-btn--sm" onclick={() => (editingNote = false)}>{t('cplug.huddle.row.note_cancel')}</button>
            <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm" data-task-manager-note-save={item.id} onclick={() => void commitNote()}>{t('cplug.huddle.row.note_save')}</button>
          </div>
        </div>
      {/if}
      {#if wrapped}{#if !options.tabbedDetail}<CrosstalkTrail {item} />{/if}{:else}<HuddleThread {item} closed={!!decisionKeys(item)} firstBubble conversation={!options.tabbedDetail} />{/if}
      <SwarmDecisionKeys {item} />
    </div>
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<li class="hdr" bind:this={row} class:hdr--wrapped={wrapped} class:tkm--placeholder={dragging} class:tkm--asking={asking} class:tkm--open={open} class:tkm--info={isInfo(item)}
    class:tkm--focus={focused} style:--_state={stripe} data-task-manager-density={density} data-row-icons={options.drawerIcons ? 'drawer' : undefined} data-huddle-item={item.id} data-state={item.state} data-status={status} data-task-manager-signal={signal ?? undefined} data-task-manager-marker={marker ?? undefined}
    data-kind={item.kind || undefined} data-by={item.created_by} data-task-manager-focused={focused ? 'on' : undefined}
    onkeydown={(event) => forwardMenuKey(event, row ?? null)} {...menuRightClick(() => taskRowMenu(item))}>
  {#if wrapped}
    
    <TaskWrapper state={taskState} onStateChange={peek} toggleProps={toggleProps}>
      {#snippet lead()}{@render leadChrome()}{/snippet}
      {#snippet head()}{@render headLine()}{/snippet}
      {#snippet keys()}{#if open}{@render keysChrome()}{/if}{/snippet}
      {#snippet tabs()}{@render detailBody()}{/snippet}
    </TaskWrapper>
  {:else}
    {@render leadChrome()}
    <button type="button" class="tkm-head" aria-expanded={open} aria-label={open ? item.text : undefined} data-task-manager-toggle={item.id} onclick={() => toggleRow(item.id)}>
      {@render headLine()}
    </button>
    {#if open}
      {@render keysChrome()}
      {@render detailBody()}
    {/if}
    {#if !open}<TaskManagerRowPeek {item} {parts} />{/if}
    {#if review && (open ? !options.tabbedDetail : parts.review)}<HuddleReview block={review} id={item.id} answer={reviewAnswer} issue={item.github_issue} />{/if}
    {#if !open && parts.reply && !parts.questions}<div class="tkm-reply"><HuddleReply {item} onRow /></div>{/if}
  {/if}
</li>

<style>
  @layer components {
    .hdr {
      --_state: var(--oc-line-rule);
      --_fs: var(--hd-fs, var(--oc-fs-label));
      position: relative;
      container: hdr / inline-size;
      display: grid;
      --_grip-w: 12px;
      --_check-w: 14px;
      --_mark-w: 12px;
      --_col-gap: 8px;
      --hdr-lead: calc(var(--_check-w) + var(--_mark-w) + 2 * var(--_col-gap));
      grid-template-columns: var(--_grip-w) var(--_check-w) var(--_mark-w) minmax(0, 1fr) auto;
      align-items: center;
      column-gap: var(--_col-gap);
      min-height: 28px;
      padding: 4px 8px 4px 18px;
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
      background: var(--oc-ground-panel);
      color: var(--oc-text-secondary);
      font-size: var(--_fs);
      line-height: 16px;
    }

    .tkm-state {
      position: absolute;
      inset: 0 auto 1px 5px;
      width: 2px;
      background: var(--_state);
    }

    .tkm-marker {
      position: absolute;
      top: 50%;
      left: 9px;
      display: inline-flex;
      transform: translateY(-50%);
    }

    .tkm--open .tkm-marker {
      top: 14px;
    }

    .hdr[data-status='question'] .tkm-state {
      width: 3px;
    }

    .hdr[data-task-manager-signal='attention'] .tkm-state,
    .hdr[data-task-manager-signal='unread'] .tkm-state {
      width: 4px;
    }

    .tkm-state[data-task-manager-signal='info'] {
      background: repeating-linear-gradient(to bottom, var(--_state) 0 4px, var(--oc-violet) 4px 8px);
    }

    :global(.hdr.tkm--lifted) {
      background: var(--oc-ground-raised);
      box-shadow: var(--oc-shadow-lift), inset 0 0 0 1px var(--oc-line-frame);
    }

    .tkm--placeholder {
      opacity: 0.35;
    }

    .tkm--focus {
      background: var(--oc-orange-tint);
      box-shadow: inset 0 0 0 1px var(--oc-orange-dim);
    }

    .tkm--open {
      grid-template-rows: auto auto auto auto;
      align-items: start;
      padding-top: 8px;
      padding-bottom: 12px;
    }

    .tkm--open :global(.tkm-review) {
      grid-row: 3;
    }

    .tkm--open :is(.tkm-grip, .tkm-grip-gap) {
      grid-row: 1 / -1;
      align-self: center;
    }

    .hdr[data-row-icons='drawer'] {
      --_grip-w: 14px;
      --_mark-w: 14px;
    }

    .tkm-grip-gap {
      grid-column: 1;
      width: var(--_grip-w);
    }

    .tkm-grip {
      grid-column: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: var(--_grip-w);
      height: 16px;
      padding: 0;
      border: 1px solid transparent;
      border-radius: var(--oc-radius-sm);
      background: none;
      color: var(--oc-text-dim);
      cursor: grab;
      touch-action: none;
    }

    .tkm-grip:hover {
      color: var(--oc-text-secondary);
    }

    .tkm--placeholder .tkm-grip {
      cursor: grabbing;
    }

    .hdr :global(.oc-check) {
      grid-column: 2;
      grid-row: 1;
      justify-content: center;
      width: 14px;
      height: 16px;
      min-height: 0;
      gap: 0;
      overflow: visible;
    }

    .tkm-head {
      grid-column: 3 / 5;
      grid-row: 1;
      display: grid;
      grid-template-columns: subgrid;
      align-items: center;
      min-width: 0;
      padding: 0;
      border: 1px solid transparent;
      background: none;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
    }

    .tkm-status {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: var(--_mark-w);
      height: 16px;
      color: var(--_icon);
      cursor: pointer;
    }

    .hdr-line {
      --tkm-title-min: 12em;
      min-width: 0;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
    }

    .tkm-text {
      flex: 1 1 var(--tkm-title-min);
      min-width: 0;
      margin: 0;
      color: var(--oc-text-primary);
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }

    .tkm-text--clip {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .tkm-text--clip2 {
      display: -webkit-box;
      overflow: hidden;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      line-clamp: 2;
    }

    .hdr[data-state='done'] .tkm-text {
      color: var(--oc-text-muted);
    }

    .tkm--info .tkm-text {
      color: var(--oc-text-muted);
      font-style: italic;
    }

    .tkm-tag,
    .tkm-asking,
    .hdr-label {
      flex: none;
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      line-height: 16px;
      text-transform: uppercase;
    }

    .tkm-tag {
      color: var(--oc-text-muted);
      cursor: pointer;
    }

    .tkm-asking {
      color: var(--oc-yellow);
    }

    .hdr-keys {
      grid-column: 5;
      grid-row: 1;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin: -2px -4px -2px 0;
    }

    .tkm-key {
      --oc-ibtn-size: 20px;
    }

    .tkm-remove:hover {
      color: var(--oc-coral);
    }

    .tkm-reply {
      grid-column: 4 / 6;
      grid-row: 4;
      min-width: 0;
      margin-top: 4px;
      margin-left: calc(-1 * var(--hdr-lead, 0px));
    }

    .tkm-detail {
      grid-column: 4 / 6;
      grid-row: 4;
      display: flex;
      flex-direction: column;
      gap: 12px;
      min-width: 0;
      margin-top: 12px;
    }

    :global(.tkm-lead-host > :not(.tkm-posts, .hdt, .tkm-peek-desc, .tkm-latest)) {
      margin-left: calc(-1 * var(--hdr-lead, 0px));
    }

    .tkm-note {
      margin: 0;
      padding: 0 0 0 8px;
      box-shadow: inset 1px 0 0 var(--oc-orange-dim);
      color: var(--oc-text-primary);
      line-height: 1.5;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .hdr-label {
      display: block;
      color: var(--oc-orange);
    }

    .tkm-note-edit {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .tkm-note-input {
      width: 100%;
      padding: 2px 6px;
      font-size: var(--_fs);
      resize: vertical;
    }

    .tkm-note-actions {
      display: flex;
      justify-content: flex-end;
      gap: 4px;
    }

    .tkm-by {
      flex: none;
      display: inline-flex;
      align-items: center;
      width: var(--_mark-w);
      height: var(--_mark-w);
      color: var(--oc-text-muted);
    }

    .tkm-by :global(svg) {
      width: var(--_mark-w);
      height: var(--_mark-w);
    }

    .tkm-posts-n {
      flex: none;
      display: inline-flex;
      align-items: center;
      gap: 2px;
      color: var(--_post);
      font-size: var(--oc-fs-micro);
      font-variant-numeric: tabular-nums;
    }

    .tkm-count {
      flex: none;
      display: inline-flex;
      align-items: center;
      gap: 2px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      font-variant-numeric: tabular-nums;
    }

    .tkm-when {
      flex: none;
      min-width: 0;
      max-width: 100%;
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1-5);
    }

    .tkm-due {
      flex: none;
      display: inline-flex;
      align-items: center;
      gap: 3px;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-micro);
      white-space: nowrap;
    }

    .hdr--wrapped .tkm-due[data-task-manager-due] {
      color: var(--oc-scheduled);
      font-size: var(--oc-fs-label);
      font-weight: 600;
    }

    .hdr--wrapped .tkm-due[data-task-manager-due][data-due-state='fired'] {
      color: var(--oc-text-muted);
    }

    .hdr--wrapped .tkm-due[data-task-manager-due][data-due-state='failed'] {
      color: var(--oc-coral);
    }

    .tkm-due[data-due-state='fired'] {
      color: var(--oc-text-muted);
    }

    .tkm-due[data-due-state='failed'] {
      color: var(--oc-coral);
    }

    .tkm-due[data-wait-overdue='true'] {
      color: var(--oc-coral);
    }

    .hdr.hdr--wrapped,
    .hdr.hdr--wrapped.tkm--open {
      display: block;
      min-height: 0;
      padding: 0;
      --hdr-lead: 0px;
    }

    .hdr--wrapped :global(.oc-task) {
      background: none;
      box-shadow: none;
    }

    .hdr--wrapped .hdr-line {
      flex: 1 1 auto;
    }

    @container hdr (max-width: 22rem) {
      .tkm-reply,
      .tkm-detail {
        grid-column: 1 / -1;
      }

      .tkm-detail,
      .tkm-reply {
        --hdr-lead: 0px;
      }
    }
  }
</style>
