
<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import State from '../../base/State.svelte';
  import { boundary, ensureReport, feed, loadBoundary, loadOlder, lookup, reports } from '../feed-store.svelte';
  import { startFromTemplate } from '../list-state.svelte';
  import { previousIndex } from '../logic/diff';
  import { slotOf, type FeedRow } from '../logic/feed';
  import { TEMPLATES, templateNameKey } from '../logic/templates';
  import type { FeedRun } from '../logic/types';
  import { isLive, runTime } from '../logic/words';
  import { data, feedParams, openNew, pageClock, reloadFeed, sessionOptions, setTab } from '../page-store.svelte';
  import { markAllRead, markRead, unread } from '../read-state.svelte';
  import { writeFeedRun } from '../route';
  import ContextColumn from './ContextColumn.svelte';
  import { buildModel, isChangedRow, isUnreadRow, whereWords } from './feed-model';
  import { feedKeyAction, inField } from './feed-keys';
  import { clearAllFilters, anyFilter, FIRST_LIMIT, fv, isPhone, loadOutside, MORE_LIMIT, openAutomation, outside } from './feed-state.svelte';
  import FeedList from './FeedList.svelte';
  import FeedTop from './FeedTop.svelte';
  import Reader from './Reader.svelte';
  import ReaderSheet from './ReaderSheet.svelte';
  import './feed.css';
  import { firstPick, indexOf, nextUnread, walkRows, type FlatRow } from '../logic/feed';

  let scrollTick = $state(0);

  const clock = $derived(pageClock());
  const byAuto = $derived(new Map(data.automations.map((a) => [a.automation_id, a])));
  const serverFiltered = $derived(Object.keys(feedParams() ?? {}).length > 0);
  const clientFiltered = $derived(!!(fv.q.trim() || fv.changedOnly || fv.unreadOnly));

  const oldestOf = $derived.by(() => {
    const out = new Map<string, FeedRun>();
    for (const r of feed.runs) out.set(r.automation_id, r);
    return out;
  });
  const older = $derived.by(() => {
    const out: FeedRun[] = [];
    for (const [aid, r] of oldestOf) {
      const b = boundary[`${aid}:${r.run_id}`];
      if (b) out.push(b);
    }
    return out;
  });

  $effect(() => {
    if (feed.status !== 'ready' || (feed.nextBefore === null && !serverFiltered)) return;
    for (const [aid, r] of oldestOf) untrack(() => void loadBoundary(aid, r.run_id));
  });

  const model = $derived(
    buildModel({
      runs: feed.runs,
      older,
      lookup,
      q: fv.q,
      changedOnly: fv.changedOnly,
      unreadOnly: fv.unreadOnly,
      unread: { seenAt: unread.seenAt, read: new Set(unread.read) },
      clock,
      tz: data.tz,
      now: data.now,
      limit: fv.limit,
      expanded: fv.expanded,
      retryMax: (id) => byAuto.get(id)?.retry_max ?? 0,
    }),
  );

  $effect(() => {
    void JSON.stringify(feedParams());
    untrack(() => (fv.limit = FIRST_LIMIT));
  });

  const selectedId = $derived(data.feedRunId);
  const current = $derived<FeedRun | null>(
    selectedId ? (feed.runs.find((r) => r.run_id === selectedId) ?? (outside.run?.run_id === selectedId ? outside.run : null) ?? older.find((r) => r.run_id === selectedId) ?? null) : null,
  );

  $effect(() => {
    const id = selectedId;
    if (!id || feed.status !== 'ready' || feed.runs.some((r) => r.run_id === id)) return;
    untrack(() => void loadOutside(id));
  });
  $effect(() => {
    const run = outside.run;
    if (run && run.run_id === selectedId) untrack(() => void loadBoundary(run.automation_id, run.run_id));
  });

  $effect(() => {
    if (selectedId || feed.status !== 'ready' || !model.rows.length) return;
    const first = firstPick(model.rows, model.info, model.unread);
    if (first) untrack(() => (data.feedRunId = first.run.run_id));
  });

  $effect(() => {
    const run = current;
    if (run && run.has_report && !isLive(run.status) && !reports[run.run_id]) untrack(() => ensureReport(run.run_id));
  });

  const slot = $derived(current ? slotOf(current as FeedRow, lookup) : { state: 'pending' as const });
  const automation = $derived(current ? byAuto.get(current.automation_id) : undefined);

  const prev = $derived.by(() => {
    if (!current) return null;
    const seen = new Set<string>();
    const list: FeedRun[] = [];
    for (const r of [...feed.runs, ...older, ...(outside.run ? [outside.run] : []), ...Object.values(boundary).filter((b): b is FeedRun => !!b)]) {
      if (r.automation_id !== current.automation_id || seen.has(r.run_id)) continue;
      seen.add(r.run_id);
      list.push(r);
    }
    list.sort((a, b) => (a.number != null && b.number != null && a.number !== b.number ? b.number - a.number : runTime(b) - runTime(a)));
    const at = list.findIndex((r) => r.run_id === current.run_id);
    const p = at < 0 ? -1 : previousIndex(list, at, lookup);
    return p >= 0 ? { run: list[p]!, slot: slotOf(list[p] as FeedRow, lookup) } : null;
  });

  const runsLine = $derived(clientFiltered ? model.counts.runs : feed.total);
  const restMembers = $derived(model.pg.rest.reduce((n, e) => n + e.members.length, 0));
  const left = $derived(clientFiltered ? restMembers : Math.max(0, feed.total - model.pg.runsShown));
  const hasMore = $derived(model.pg.rest.length > 0 || feed.nextBefore !== null);

  const nameOf = (run: FeedRow): string => run.automation_name || byAuto.get(run.automation_id)?.name || t('automations.page.reader.removed');
  const whereOf = (run: FeedRow): string => whereWords(byAuto.get(run.automation_id), data.projects, sessionOptions());
  const retryMaxOf = (run: FeedRow): number => byAuto.get(run.automation_id)?.retry_max ?? 0;

  function setRun(id: string, o: { sheet?: boolean; scroll?: boolean }): void {
    data.feedRunId = id;
    const row = model.rows[indexOf(model.rows, id, fv.expanded)];
    markRead(row && row.kind === 'fold' ? row.entry.members.map((m) => m.run_id) : [id]);
    if (o.sheet && isPhone()) fv.sheet = true;
    if (!isPhone()) writeFeedRun(id);
    if (o.scroll) scrollTick += 1;
  }

  function toggleFold(key: string): void {
    fv.expanded = { ...fv.expanded, [key]: !fv.expanded[key] };
  }

  function pick(key: string): void {
    const row = model.rows.find((x) => x.key === key);
    if (!row) return;
    setRun(row.run.run_id, { sheet: true });
    if (row.kind === 'fold') toggleFold(row.key);
  }

  function walk(dir: 1 | -1, pred: (x: FlatRow) => boolean = () => true): boolean {
    const from = selectedId ? indexOf(model.rows, selectedId, fv.expanded) : -1;
    const to = walkRows(model.rows, from, dir, pred);
    if (to < 0) return false;
    setRun(model.rows[to]!.run.run_id, { scroll: true });
    return true;
  }

  function nextChanged(dir: 1 | -1): void {
    if (!walk(dir, (x) => isChangedRow(model, x))) data.notice = t(dir > 0 ? 'automations.page.toast.no_older_changed' : 'automations.page.toast.no_newer_changed');
  }

  function goUnread(): void {
    const from = selectedId ? indexOf(model.rows, selectedId, fv.expanded) : -1;
    const hit = nextUnread(model.rows, from, (x) => isUnreadRow(model, x));
    if (!hit) {
      data.notice = t('automations.page.toast.nothing_unread');
      return;
    }
    setRun(model.rows[hit.index]!.run.run_id, { scroll: true });
    if (hit.wrapped) data.notice = t('automations.page.toast.top_of_unread');
  }

  function onKey(e: KeyboardEvent): void {
    if (inField(e.target) || feed.status === 'error' || !model.rows.length) return;
    const onList = e.target === document.getElementById('ap-fd-list') || e.target === document.body;
    const action = feedKeyAction(e, { onList, sheetOpen: fv.sheet && isPhone() });
    if (!action) return;
    if (action === 'next') (e.preventDefault(), walk(1));
    else if (action === 'prev') (e.preventDefault(), walk(-1));
    else if (action === 'next_changed') nextChanged(1);
    else if (action === 'prev_changed') nextChanged(-1);
    else if (action === 'next_unread') goUnread();
    else if (action === 'toggle_fold') {
      const i = selectedId ? indexOf(model.rows, selectedId, fv.expanded) : -1;
      const x = model.rows[i];
      if (x) toggleFold(x.kind === 'member' ? x.entry.key : x.key);
    } else if (action === 'search') (e.preventDefault(), document.getElementById('f-q')?.focus());
    else if (action === 'close_sheet') fv.sheet = false;
  }

  onMount(() => {
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });

  async function loadOlderPage(): Promise<void> {
    const params = feedParams();
    if (model.pg.rest.length === 0 && feed.nextBefore !== null && params) await loadOlder(params);
    fv.limit += MORE_LIMIT;
  }

  function fromTemplate(i: number): void {
    setTab('automations');
    startFromTemplate(TEMPLATES[i]!);
  }

  function newAutomation(): void {
    setTab('automations');
    openNew();
  }

  const refreshKey = $derived(`${automation?.newest_number ?? ''}:${automation?.recent?.[0]?.status ?? ''}`);
</script>

<div class="ap-sx" id="ap-sv" data-feed-tab>
  <section class="ap-feed" id="ap-feed" aria-label={t('automations.page.feed.list.aria')}>
    <FeedTop runs={runsLine} changed={model.counts.changed} unread={model.counts.unread} anyFilter={anyFilter()} onMarkRead={() => markAllRead()} onClear={clearAllFilters} />
    <FeedList
      {model}
      {clock}
      selectedRunId={selectedId}
      expanded={fv.expanded}
      failed={feed.status === 'error'}
      failedText={feed.error}
      anyFilter={anyFilter()}
      total={clientFiltered ? model.counts.runs : feed.total}
      {left}
      {hasMore}
      loadingMore={feed.loadingMore}
      {nameOf}
      {whereOf}
      {retryMaxOf}
      onPick={pick}
      onLoadOlder={() => void loadOlderPage()}
      onRetry={() => void reloadFeed()}
      onClear={clearAllFilters}
      {scrollTick}
    />
    <div class="ap-keys" data-feed-keys>
      <span>
        <kbd>j</kbd><kbd>k</kbd> {t('automations.page.keys.runs')}
        <kbd>u</kbd> {t('automations.page.keys.next_changed')}
        <kbd>n</kbd> {t('automations.page.keys.next_unread')}
        <kbd>o</kbd> {t('automations.page.keys.unfold')}
        <kbd>/</kbd> {t('automations.page.keys.search')}
      </span>
    </div>
  </section>

  <ReaderSheet open={fv.sheet} swapKey={current?.run_id ?? 'none'} onWalk={(dir) => void walk(dir)}>
    {#if current}
      <Reader
        run={current}
        {automation}
        automationName={nameOf(current as FeedRow)}
        {slot}
        {prev}
        {clock}
        tz={data.tz}
        now={data.now}
        retryMax={automation?.retry_max ?? 0}
        onBack={() => (fv.sheet = false)}
        onPrev={() => void walk(-1)}
        onNext={() => void walk(1)}
        onNextChanged={() => nextChanged(1)}
        onOpenAuto={() => openAutomation(current.automation_id, current.run_id)}
        onRetryReport={() => {
          delete reports[current.run_id];
          ensureReport(current.run_id);
        }}
      />
    {:else}
      <div class="ap-rd-none" data-reader-empty>
        {#if feed.status === 'error'}
          <State kind="error" title={feed.error} role="alert">
            {#snippet actions()}<Button size="sm" data-act="retry-list" onclick={() => void reloadFeed()}>{t('automations.page.try_again')}</Button>{/snippet}
          </State>
        {:else}
          <State title={t('automations.empty')} hint={t('automations.page.reader.none_title')}>
            {#snippet actions()}
              {#each TEMPLATES as tpl, i (tpl.id)}<Button size="sm" data-tpl={i} disabled={!data.targets} onclick={() => fromTemplate(i)}>{t(templateNameKey(tpl))}</Button>{/each}
              <Button variant="confirm" size="sm" data-act="new" disabled={!data.targets} onclick={newAutomation}>{t('automations.new')}</Button>
            {/snippet}
          </State>
        {/if}
      </div>
    {/if}
  </ReaderSheet>

  {#if current}
    <ContextColumn
      automationId={current.automation_id}
      name={nameOf(current as FeedRow)}
      currentRunId={current.run_id}
      {refreshKey}
      {clock}
      tz={data.tz}
      now={data.now}
      onPick={(id) => setRun(id, { sheet: true })}
    />
  {:else}
    <aside class="ap-cx" aria-hidden="true"></aside>
  {/if}
</div>
