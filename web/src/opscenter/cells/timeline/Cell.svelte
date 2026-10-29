<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  const isBool = (value: unknown): value is boolean => typeof value === 'boolean';

  export const TIMELINE_WIDGET = defineWidget({
    id: 'core.timeline',
    scope: 'session',
    actions: [
      { id: 'show-bookmarks', labelKey: 'opscenter.cell.timeline.filter.bookmarks', kind: 'switch', group: 'show' },
      { id: 'show-compacts', labelKey: 'opscenter.cell.timeline.filter.compacts', kind: 'switch', group: 'show' },
      { id: 'show-restarts', labelKey: 'opscenter.cell.timeline.filter.restarts', kind: 'switch', group: 'show' },
      { id: 'show-sleeping', labelKey: 'opscenter.cell.timeline.filter.sleeps', kind: 'switch', group: 'show' },
      { id: 'show-restores', labelKey: 'opscenter.cell.timeline.filter.restores', kind: 'switch', group: 'show' },
      { id: 'squeeze-sleeps', labelKey: 'opscenter.cell.timeline.view.action.squeeze', kind: 'switch', group: 'view' },
      { id: 'fork', labelKey: 'opscenter.cell.timeline.view.action.branch', group: 'point' },
      { id: 'rewind-here', labelKey: 'opscenter.cell.timeline.view.action.rewind', group: 'point' },
      { id: 'bookmark', labelKey: 'opscenter.cell.timeline.view.action.bookmark', group: 'point' },
      { id: 'open-copy', labelKey: 'opscenter.cell.timeline.view.action.copy', group: 'point' },
      { id: 'open-conversation', labelKey: 'opscenter.cell.timeline.view.action.open', group: 'point' },
    ],
    state: { squeeze: { home: 'device', default: true, valid: isBool } },
  });
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import { activeTerminalSessionId } from '../../lib/active-terminal';
  import { sessions } from '../../api';
  import { sessionTimeline, releaseSessionTimeline } from '../../api/session-timeline.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import FacetSelect from '../../ui/FacetSelect.svelte';
  import State from '../../../lib/base/State.svelte';
  import { useHeaderGroup } from '../../shell/frame-header.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import type { WidgetStatus } from '../../widgets/shell/widget-status';
  import { liveRowIds } from '../bookmarks/live-rows';
  import { TimelineActions, offersFor } from './actions.svelte';
  import MarkCard from './MarkCard.svelte';
  import TimelineList from './TimelineList.svelte';
  import { timelineFilters } from './filters.svelte';
  import { filterCounts, phoneRows } from './model';
  import type { FilterKey, Mark, SessionTimeline } from './types';
  import Detail from './Detail.svelte';
  import KindKey from './KindKey.svelte';
  import Column from './Column.svelte';
  import { layoutColumn, stepColumn } from './column';
  import { frameFor, type Item, type Move, type PointAction } from './plot-model';
  import { tx } from './strings';

  let props: CellProps = $props();
  const { scope = null, width, height, phone = false, instance } = $derived(props);

  const PICKER_HEAD_MIN_WIDTH = 420;
  const pickKey = (): string => `oc.timeline.pick:${instance}`;

  function loadPick(): string {
    try {
      return globalThis.localStorage?.getItem(pickKey()) ?? '';
    } catch {
      return '';
    }
  }

  const actions = new TimelineActions();
  let selectedKey = $state<string | null>(null);
  let hoverKey = $state<string | null>(null);
  let activeKey = $state<string | null>(null);

  const widget = useWidget(TIMELINE_WIDGET, () => props, () => ({
    'show-bookmarks': filterBinding('bookmarks'),
    'show-compacts': filterBinding('compacts'),
    'show-restarts': filterBinding('restarts'),
    'show-sleeping': filterBinding('sleeps'),
    'show-restores': filterBinding('restores'),
    'squeeze-sleeps': { on: squeeze, run: () => { widget.state.squeeze = !squeeze; } },
    fork: actionBinding('branch'),
    'rewind-here': actionBinding('rewind'),
    bookmark: actionBinding('bookmark'),
    'open-copy': actionBinding('copy'),
    'open-conversation': actionBinding('open'),
  }));
  const squeeze: boolean = $derived(widget.state.squeeze);

  let pick = $state(loadPick());
  const sessionId = $derived(scope?.sessionId || pick || activeTerminalSessionId());
  const infos = $derived(sessions.data ?? []);
  const info = $derived(infos.find((s) => s.session.id === sessionId) ?? null);
  const rowId = $derived(typeof info?.session_row_id === 'number' ? info.session_row_id : null);
  const projectId = $derived(typeof info?.project_id === 'number' ? info.project_id : (props.scope?.projectId ?? null));
  const live = $derived(rowId !== null && liveRowIds(infos).has(rowId));
  const pickerOptions = $derived([
    { value: '', label: t('opscenter.cell.timeline.picker.focused') },
    ...infos.filter((s) => typeof s.session_row_id === 'number').map((s) => ({ value: s.session.id, label: s.label || s.tmux_session || s.session.id })),
  ]);

  let res = $state.raw<Resource<SessionTimeline> | null>(null);
  $effect(() => {
    const id = rowId;
    selectedKey = hoverKey = activeKey = null;
    actions.clearPeeks();
    if (id === null) { res = null; return; }
    res = sessionTimeline(id);
    return () => releaseSessionTimeline(id);
  });

  const data = $derived(res?.data ?? null);
  const status = $derived<WidgetStatus>(
    !sessionId || rowId === null ? 'none' : !data ? (res && res.status !== 'loading' ? 'error' : 'loading') : data.bars.length === 0 ? 'empty' : 'ready',
  );
  const note = $derived(status === 'none' ? t('opscenter.cell.timeline.none') : status === 'error' ? t('opscenter.cell.timeline.unknown')
    : status === 'empty' ? tx('none.bars') : status === 'loading' ? t('opscenter.cell.timeline.loading') : '');
  const frame = $derived(frameFor(phone, height > 0 && Number.isFinite(height) ? height : null));
  const column = $derived(data && frame.body === 'column' ? layoutColumn(data, timelineFilters.value, frame.plotPx, squeeze) : null);
  const items = $derived(column ? new Map(column.items.map((c): [string, Item] => [c.item.key, c.item])) : new Map<string, Item>());
  const counts = $derived(data ? filterCounts(data) : { bookmarks: 0, compacts: 0, restarts: 0, sleeps: 0, restores: 0 });
  const allHidden = $derived(Object.values(timelineFilters.value).every((on) => !on));

  function resolve(key: string | null): Item | null {
    if (!key) return null;
    const hit = items.get(key);
    if (hit) return hit;
    const mark = key.startsWith('mark:') ? data?.marks.find((m) => `mark:${m.id}` === key) : undefined;
    return mark ? { key, kind: 'mark', mark, x: 0 } : null;
  }

  const selected = $derived(resolve(selectedKey));
  const shown = $derived(selected ?? resolve(hoverKey));
  const pickedMark = $derived<Mark | null>(selected?.kind === 'mark' ? selected.mark : null);
  const offers = $derived.by((): Record<PointAction, boolean> => {
    if (pickedMark && data) {
      const o = offersFor(pickedMark, data);
      return { branch: o.cut, rewind: o.cut, bookmark: o.bookmark, copy: o.copy, open: true };
    }
    return { branch: false, rewind: false, bookmark: false, copy: false, open: selected?.kind === 'conversation' };
  });

  $effect(() => {
    const mark = pickedMark;
    if (mark && rowId !== null && data && offersFor(mark, data).peek) untrack(() => void actions.peek(rowId, mark));
  });

  function filterBinding(key: FilterKey): { on: boolean; run: () => void } {
    return { on: timelineFilters.value[key], run: () => timelineFilters.toggle(key) };
  }

  function blockedFor(id: PointAction): string {
    if (!selected) return tx('action.blocked.pick');
    if (!offers[id]) return tx('action.blocked.offer');
    if (actions.busy !== null) return tx('action.blocked.busy');
    if (id === 'rewind' && (!actions.armed || !live)) return tx('action.blocked.arm');
    return '';
  }

  function actionBinding(id: PointAction): { run: () => void; blocked: string } {
    return { run: () => runAction(id), blocked: blockedFor(id) };
  }

  function runAction(id: PointAction): void {
    if (!data || blockedFor(id)) return;
    if (id === 'open') {
      const conversation = selected?.kind === 'conversation' ? selected.bar.conversation_id : pickedMark?.conversation_id;
      if (conversation) void actions.open(data, conversation, projectId);
      return;
    }
    if (!pickedMark || rowId === null) return;
    if (id === 'branch') void actions.branch(rowId, pickedMark);
    else if (id === 'rewind') void actions.rewind(rowId, pickedMark);
    else if (id === 'bookmark') void actions.bookmark(rowId, pickedMark);
    else void actions.openCopy(pickedMark);
  }

  function select(key: string): void {
    selectedKey = selectedKey === key ? null : key;
    activeKey = key;
  }

  function move(m: Move): string | null {
    if (!column) return null;
    activeKey = stepColumn(column, activeKey ?? stepColumn(column, null, m), m);
    hoverKey = activeKey;
    return activeKey;
  }

  const pickerPlace = useHeaderGroup(() => (scope === null && width >= PICKER_HEAD_MIN_WIDTH ? pickerGroup : null));
  const pickerInBody = $derived(scope === null && !pickerPlace.up);

  function choose(value: string): void {
    pick = value;
    try {
      globalThis.localStorage?.setItem(pickKey(), value);
    } catch {
    }
  }

  const KEY_MIN_WIDTH = 260;

  function keyForm(place: 'header' | 'body' | 'corner'): 'glyphs' | 'counts' | 'words' {
    const w = place === 'header' ? width - 220 : width;
    return w >= 540 ? 'words' : w >= 200 ? 'counts' : 'glyphs';
  }

  function selectListMark(mark: Mark): void {
    select(`mark:${mark.id}`);
  }
</script>

{#snippet pickerGroup()}
  <FacetSelect label={t('opscenter.cell.timeline.picker.label')} value={pick} options={pickerOptions} onChange={choose} id="timeline-session" />
{/snippet}

{#snippet controls(place: 'header' | 'body' | 'corner')}
  {#if data && place !== 'corner' && (place === 'body' || width >= KEY_MIN_WIDTH)}
    <KindKey filters={timelineFilters.value} {counts} form={keyForm(place)} onToggle={(key) => timelineFilters.toggle(key)} />
  {/if}
{/snippet}

{#snippet listCard(mark: Mark)}
  {#if data && rowId !== null}
    <MarkCard {data} {mark} {rowId} {live} {actions} menu={true} {projectId} onClose={() => (selectedKey = null)} />
  {/if}
{/snippet}

<div class="oc-tl">
{#if pickerInBody}<div class="oc-tl-top">{@render pickerGroup()}</div>{/if}
<div class="oc-tl-shell">
<WidgetShell {widget} {status} {note} {controls}>
  {#if data}
    <div class="tlx" data-timeline data-session={sessionId || undefined} data-body={frame.body}
      style:--tlx-pad={`${frame.pad}px`} style:--tlx-detail={`${frame.detailPx}px`}>
      {#if frame.body === 'list'}
        <TimelineList rows={phoneRows(data, timelineFilters.value)} selectedId={pickedMark?.id ?? null} onSelect={selectListMark} card={listCard} />
      {:else if column}
        <div class="tlx-main">
          <Column {column} {data} active={activeKey} selected={selectedKey}
            onHover={(key) => (hoverKey = key)} onSelect={select} onMove={move} onEscape={() => (selectedKey = null)} />
          {#if allHidden}<State inline title={tx('none.shown')} />{/if}
        </div>
        <div class="tlx-detail">
          <Detail {data} item={shown} pinned={selected !== null} {offers} armed={actions.armed} {live}
            busy={actions.busy !== null} notice={actions.notice} peek={pickedMark ? (actions.peeks[pickedMark.id] ?? null) : null}
            onPick={(key) => { selectedKey = key; }} onAction={runAction} onArm={(on) => { actions.armed = on; }} onClose={() => (selectedKey = null)} />
        </div>
      {/if}
    </div>
  {/if}
</WidgetShell>
</div>
</div>

<style>
  @layer components {
    .oc-tl {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 0;
    }

    .oc-tl-top {
      flex: 0 0 auto;
      padding: var(--oc-space-1) var(--oc-space-2) 0;
      min-width: 0;
    }

    .oc-tl-shell {
      flex: 1 1 0;
      min-height: 0;
    }

    .tlx {
      display: grid;
      grid-template-rows: max-content var(--tlx-detail);
      gap: var(--tlx-pad);
      height: 100%;
      min-height: 0;
      padding: var(--tlx-pad);
      overflow-y: auto;
      box-sizing: border-box;
      font-family: var(--font-mono);
    }

    .tlx[data-body='list'] {
      display: block;
      overflow-y: auto;
    }

    .tlx-main {
      display: flex;
      flex-direction: column;
      min-height: 0;
      min-width: 0;
      overflow: hidden;
    }

    .tlx-detail {
      min-height: 0;
      min-width: 0;
      overflow-y: auto;
      box-shadow: inset 0 var(--oc-border) 0 var(--oc-line-faint);
      padding-top: var(--oc-space-1);
    }
  }
</style>
