<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';
  import { HISTORY_SCOPES, SCOPE_MEMORY_KEY, type HistoryScope } from '../../../lib/crosstalk/history/history-model';
  import { isSeenMarks, isSplit, NO_MARKS, STACK_SPLIT_DEFAULT } from './model';

  const isHistoryScope = (value: unknown): value is HistoryScope => HISTORY_SCOPES.includes(value as HistoryScope);

  export const CROSSTALK_WIDGET = defineWidget({
    id: 'core.crosstalk',
    scope: 'session',
    actions: [
      { id: 'close-thread', labelKey: 'crosstalk.widget.close_thread' },
      { id: 'mark-all-read', labelKey: 'crosstalk.widget.mark_all_read' },
      { id: 'scope:all', labelKey: 'crosstalk.history.scope.menu_all', kind: 'choice', group: 'scope' },
      { id: 'scope:project', labelKey: 'crosstalk.history.scope.menu_project', kind: 'choice', group: 'scope' },
      { id: 'scope:session', labelKey: 'crosstalk.history.scope.menu_session', kind: 'choice', group: 'scope' },
    ],
    state: {
      scope: { home: 'device', default: 'project', valid: isHistoryScope, legacyKey: SCOPE_MEMORY_KEY },
      seen: { home: 'device', default: NO_MARKS, valid: isSeenMarks },
      split: { home: 'device', default: STACK_SPLIT_DEFAULT, valid: isSplit },
    },
  });
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import { sessions } from '../../api';
  import { sessionScopeFor } from '../../widgets/session-scope';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget, type WidgetHandle } from '../../widgets/shell/define-widget.svelte';
  import type { WidgetStatus } from '../../widgets/shell/widget-status';
  import { t } from '../../../lib/i18n/index.svelte';
  import { clock, startClock } from '../../lib/frozen-clock.svelte';
  import { filterFor, type HistoryTarget } from '../../../lib/crosstalk/history/history-model';
  import { Conversations } from '../../../lib/crosstalk/history/conversations.svelte';
  import {
    CAPTION_FULL_WIDTH, clampSplit, countText, emptyText, isNew, layoutFor, LIST_MAX_WIDTH, LIST_SHARE, loadingText, markAllSeen,
    markSeen, NEW_WINDOW_S, scopeCaption, splitStep,
  } from './model';
  import { IconButton } from '../../../lib/base';
  import ThreadList from './ThreadList.svelte';
  import ThreadView from './ThreadView.svelte';

  let props: CellProps = $props();

  const store = new Conversations();
  const baseline = Math.floor(Date.now() / 1000) - NEW_WINDOW_S;
  let returnTo = $state<string | null>(null);
  let chosen = $state(false);
  let dragSplit = $state<number | null>(null);
  let bodyEl = $state<HTMLDivElement | null>(null);
  let bodyHeight = $state(0);

  const layout = $derived(layoutFor(props.width ?? 0, props.height ?? 0));

  const widget: WidgetHandle<typeof CROSSTALK_WIDGET> = useWidget(CROSSTALK_WIDGET, () => props, () => ({
    'close-thread': {
      run: closeThread,
      blocked: layout === 'stack' ? t('crosstalk.widget.blocked_stack') : store.openId ? '' : t('crosstalk.widget.blocked_none_open'),
    },
    'mark-all-read': { run: markAll, blocked: freshCount > 0 ? '' : t('crosstalk.widget.blocked_nothing_new') },
    'scope:all': { run: () => (widget.state.scope = 'all'), on: widget.state.scope === 'all' },
    'scope:project': { run: () => (widget.state.scope = 'project'), on: widget.state.scope === 'project' },
    'scope:session': { run: () => (widget.state.scope = 'session'), on: widget.state.scope === 'session' },
  }));

  const resolved = $derived(props.scope ?? sessionScopeFor(sessions.data, widget.sessionId));
  const target = $derived<HistoryTarget | null>(resolved
    ? { sessionId: resolved.sessionId, rowId: resolved.rowId, projectId: resolved.projectId }
    : null);
  const answer = $derived(filterFor(widget.state.scope, target));
  const filterKey = $derived('filter' in answer ? JSON.stringify(answer.filter) : '');

  const row = $derived((sessions.data ?? []).find((info) => info.session?.id === resolved?.sessionId) as
    { label?: string | null; project_name?: string | null; tmux_session?: string } | undefined);
  const subject = $derived(widget.state.scope === 'project'
    ? row?.project_name ?? ''
    : row?.label || row?.tmux_session || '');

  $effect(() => {
    void filterKey;
    untrack(() => {
      const filter = 'filter' in answer ? answer.filter : null;
      chosen = false;
      store.setFilter(filter);
    });
  });
  $effect(() => {
    const shown = widget.visible === 'shown';
    untrack(() => store.setShown(shown));
  });
  $effect(() => store.follow());
  $effect(() => startClock());
  const nowMs = $derived((void clock.now, Date.now()));

  $effect(() => {
    const newest = store.threads[0]?.thread ?? null;
    const stacked = layout === 'stack';
    untrack(() => {
      if (stacked && !chosen && newest && store.openId !== newest) store.open(newest);
      if (!stacked && !chosen && store.openId) store.close();
    });
  });

  const marks = $derived(widget.state.seen);
  const freshCount = $derived(store.threads.filter((thread) => isNew(thread, marks, baseline)).length);
  const openThread = $derived(store.openId ? store.threads.find((thread) => thread.thread === store.openId) ?? null : null);
  const listWidth = $derived(layout === 'side' ? Math.min(LIST_MAX_WIDTH, (props.width ?? 0) * LIST_SHARE) : props.width ?? 0);
  const splitShare = $derived(dragSplit ?? widget.state.split);
  const listMax = $derived(Math.round(splitShare * (bodyHeight || props.height || 0)));

  $effect(() => {
    const open = openThread;
    if (!open || !chosen || widget.visible !== 'shown') return;
    if (isNew(open, widget.state.seen, baseline)) widget.state.seen = markSeen(widget.state.seen, open.thread, open.last_at, baseline);
  });

  function openOne(thread: string): void {
    chosen = true;
    store.open(thread);
  }

  function closeThread(): void {
    returnTo = store.openId;
    chosen = false;
    store.close();
  }

  function markAll(): void {
    widget.state.seen = markAllSeen(Math.floor(Date.now() / 1000));
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || !store.openId) return;
    event.preventDefault();
    event.stopPropagation();
    if (layout === 'stack') returnTo = store.openId;
    else closeThread();
  }

  function shareAt(event: PointerEvent): number {
    const box = bodyEl?.getBoundingClientRect();
    return box && box.height > 0 ? clampSplit((event.clientY - box.top) / box.height) : widget.state.split;
  }

  function dragStart(event: PointerEvent): void {
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    dragSplit = shareAt(event);
  }

  function dragMove(event: PointerEvent): void {
    if (dragSplit !== null) dragSplit = shareAt(event);
  }

  function dragEnd(): void {
    if (dragSplit === null) return;
    widget.state.split = dragSplit;
    dragSplit = null;
  }

  function splitKey(event: KeyboardEvent): void {
    const next = splitStep(event.key, widget.state.split);
    if (next === null) return;
    event.preventDefault();
    widget.state.split = next;
  }

  const caption = $derived(scopeCaption(widget.state.scope, subject));
  const status = $derived<WidgetStatus>('refusal' in answer ? 'none'
    : store.state === 'failed' ? 'error'
    : store.state === 'loading' ? 'loading'
    : store.threads.length === 0 ? 'empty' : 'ready');
  const note = $derived(
    'refusal' in answer
      ? answer.refusal === 'no_session'
        ? t('crosstalk.widget.no_session')
        : t('crosstalk.widget.no_project', { name: subject || t('crosstalk.widget.this_session') })
      : store.state === 'failed' ? t('crosstalk.widget.failed', { reason: store.reason })
      : store.state === 'loading' ? loadingText(widget.state.scope, subject)
      : emptyText(widget.state.scope, subject));
  const showList = $derived(!(openThread && layout === 'drill'));
</script>

{#snippet controls(place: 'header' | 'body' | 'corner')}
  <span class="xr-back" data-place={place}>
    <IconButton label={t('crosstalk.widget.back_title')} variant="quiet" icon="chevron-left" iconSize={14} data-crosstalk-back onclick={closeThread} />
  </span>
{/snippet}

<WidgetShell {widget} {status} {note} controls={store.openId && layout === 'drill' ? controls : undefined}>
  
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="xr xr--{layout}" data-crosstalk-cell data-layout={layout} data-scope={widget.state.scope} onkeydown={onKey}
    bind:this={bodyEl} bind:clientHeight={bodyHeight}>
    {#if showList}
      <div class="xr-list-pane" style:max-height={layout === 'stack' && openThread ? `${listMax}px` : null}>
        <p class="xr-cap" data-crosstalk-caption>
          <span class="xr-cap__label">{caption.label}</span>
          {#if caption.subject}<bdi class="xr-cap__subject">{caption.subject}</bdi>{/if}
          <span class="xr-cap__count">{countText(store.threads.length, freshCount, store.nextBefore != null, listWidth < CAPTION_FULL_WIDTH)}</span>
        </p>
        <ThreadList threads={store.threads} {marks} {baseline} {nowMs} width={listWidth} wrap={layout !== 'side'}
          selected={store.openId} {returnTo} more={store.nextBefore != null}
          onopen={openOne} onmore={() => void store.more()} onreturned={() => (returnTo = null)} />
      </div>
    {/if}
    {#if openThread && layout === 'stack'}
      
      
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <div class="xr-divider" class:xr-divider--drag={dragSplit !== null} role="separator" aria-orientation="horizontal"
        aria-label={t('crosstalk.widget.divider_label')} aria-valuemin={20} aria-valuemax={75} aria-valuenow={Math.round(splitShare * 100)}
        tabindex="0" title={t('crosstalk.widget.divider_title')} data-crosstalk-divider
        onpointerdown={dragStart} onpointermove={dragMove} onpointerup={dragEnd} onpointercancel={dragEnd} onkeydown={splitKey}
        ondblclick={() => (widget.state.split = splitStep('Enter', 0) ?? widget.state.split)}></div>
    {/if}
    {#if openThread}
      <ThreadView thread={openThread} messages={store.messages} readState={store.threadState} reason={store.threadReason}
        older={store.olderAt != null} {nowMs} width={layout === 'side' ? (props.width ?? 0) - listWidth : props.width ?? 0}
        wrap={layout !== 'side'} takeFocus={layout === 'drill'} reserveCorner={layout === 'drill' && !widget.frame?.drawn && !widget.frame?.suppressed}
        onolder={() => void store.older()} />
    {:else if layout === 'side'}
      <p class="xr-pick" role="status">{t('crosstalk.widget.pick')}</p>
    {/if}
  </div>
</WidgetShell>

<style>
  @layer components {
    .xr { position: relative; display: flex; flex-direction: column; flex: 1 1 auto; height: 100%; min-height: 0; font-family: var(--font-mono); font-size: var(--oc-fs-body); color: var(--oc-text-primary); }
    .xr--side { flex-direction: row; }
    .xr-list-pane { display: flex; flex-direction: column; flex: 1 1 auto; min-width: 0; min-height: 0; }
    .xr--side .xr-list-pane { flex: 0 0 42%; max-width: 420px;  box-shadow: 1px 0 0 var(--oc-line-panel); }
    .xr--stack .xr-list-pane:has(+ .xr-divider) { flex: 0 1 auto; }

    .xr-cap { display: flex; align-items: baseline; gap: var(--oc-space-2); flex: none; height: 22px; margin: 0; padding: 0 var(--oc-space-2); line-height: 22px; background: var(--oc-ground-titlerow); box-shadow: inset 0 -1px 0 var(--oc-line-panel); white-space: nowrap; overflow: hidden; }
    .xr-cap__label { flex: none; color: var(--oc-orange); font-size: var(--oc-fs-label); letter-spacing: var(--oc-tracking-label, 0.08em); text-transform: uppercase; }
    .xr-cap__subject { min-width: 0; overflow: hidden; text-overflow: ellipsis; color: var(--oc-text-secondary); font-size: var(--oc-fs-label); }
    .xr-cap__count { flex: none; margin-left: auto; color: var(--oc-text-dim); font-size: var(--oc-fs-label); }
    .xr--stack .xr-cap { flex-wrap: wrap; height: auto; min-height: 22px; white-space: normal; }
    .xr--stack .xr-cap__subject { overflow-wrap: anywhere; }

    .xr-divider { position: relative; flex: none; height: 8px; margin: -3px 0 -4px; cursor: row-resize; touch-action: none; border: 1px solid transparent; z-index: 1; }
    .xr-divider::before { content: ''; position: absolute; left: 0; right: 0; top: 3px; height: 1px; background: var(--oc-line-panel); }
    .xr-divider::after { content: ''; position: absolute; left: 50%; top: 2px; width: 24px; height: 3px; margin-left: -12px; border-top: 1px solid var(--oc-text-dim); border-bottom: 1px solid var(--oc-text-dim); opacity: 0.6; }
    .xr-divider:hover::before, .xr-divider--drag::before { background: var(--oc-text-secondary); }
    .xr-divider:hover::after, .xr-divider--drag::after { opacity: 1; }

    .xr-pick { flex: 1 1 auto; margin: 0; padding: var(--oc-space-2); color: var(--oc-text-dim); font-size: var(--oc-fs-label); }
    .xr-back { flex: none; display: inline-flex; }
    .xr-back:not([data-place="header"]) { position: absolute; top: 1px; right: var(--oc-space-1); z-index: 2; }
  }
</style>
