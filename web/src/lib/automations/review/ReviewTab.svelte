
<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Segmented from '../../base/Segmented.svelte';
  import State from '../../base/State.svelte';
  import { feed, loadOlder, lookup } from '../feed-store.svelte';
  import { isUnread, slotOf, type FeedRow } from '../logic/feed';
  import { face } from '../logic/report-rules';
  import { runTime } from '../logic/words';
  import { data, feedParams, openDrawer, pageClock, reloadFeed } from '../page-store.svelte';
  import { markAllRead, markRead, unread } from '../read-state.svelte';
  import './review.css';
  import { inField, reviewKeyAction } from './review-keys';
  import { dayGroups, listed, modeForPressed, runLines, runWord, toReviewCount, type ReviewMode } from './review-model';
  import ReviewRow from './ReviewRow.svelte';

  const FOLD_AT = 350;
  const MARK_AT = 560;

  // svelte-ignore state_referenced_locally
  let mode = $state<ReviewMode>(modeForPressed(data.pressed) ?? 'review');
  let sel = $state<string | null>(null);
  let entering = $state<Record<string, boolean>>({});
  let leaving = $state<Record<string, boolean>>({});
  let known: Set<string> | null = null;
  let host: HTMLDivElement | undefined = $state();

  const marks = $derived({ seenAt: unread.seenAt, read: new Set(unread.read) });
  const clock = $derived(pageClock());
  const shown = $derived(listed(feed.runs, mode, marks, data.now));
  const days = $derived(dayGroups(shown, clock, data.now));
  const toReview = $derived(toReviewCount(feed.unfiltered ?? feed.runs, marks, data.now));
  const pressedId = $derived(data.pressed.waiting_on_you ? 'waiting_on_you' : data.pressed.failed_24h ? 'failed_24h' : null);
  const left = $derived(Math.max(0, feed.total - feed.runs.length));
  const flat = $derived(days.flatMap((d) => d.runs));

  $effect(() => {
    const asked = modeForPressed(data.pressed);
    if (asked) untrack(() => (mode = asked));
  });

  $effect(() => {
    const ids = feed.runs.map((r) => r.run_id);
    untrack(() => {
      if (known === null) {
        if (feed.status === 'ready') known = new Set(ids);
        return;
      }
      const fresh = ids.filter((id) => !known!.has(id));
      for (const id of fresh) known!.add(id);
      if (!fresh.length) return;
      entering = { ...entering, ...Object.fromEntries(fresh.map((id) => [id, true])) };
      setTimeout(() => {
        const next = { ...entering };
        for (const id of fresh) delete next[id];
        entering = next;
      }, 400);
    });
  });

  function still(): boolean {
    return typeof matchMedia !== 'function' || matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function say(key: string): void {
    const text = t(key);
    data.notice = text;
    setTimeout(() => {
      if (data.notice === text) data.notice = '';
    }, 9000);
  }

  function good(id: string): void {
    if (still() || mode === 'all') {
      markRead([id]);
      say('automations.simple.notice.reviewed');
      return;
    }
    leaving = { ...leaving, [id]: true };
    setTimeout(() => {
      markRead([id]);
      say('automations.simple.notice.reviewed');
      const { [id]: _gone, ...rest } = leaving;
      leaving = rest;
    }, MARK_AT);
  }

  function markAll(): void {
    markAllRead();
    say('automations.simple.notice.all_reviewed');
  }

  function clearFilter(): void {
    data.pressed = {};
    mode = 'review';
    void reloadFeed();
  }

  function open(id: string): void {
    sel = id;
    openDrawer('run', id);
  }

  function rowEl(id: string): HTMLElement | null {
    return host?.querySelector<HTMLElement>(`.f-row[data-run="${CSS.escape(id)}"]`) ?? null;
  }

  function keydown(e: KeyboardEvent): void {
    if (inField(e.target) || !flat.length) return;
    const onButton = (e.target as HTMLElement | null)?.closest?.('button') != null;
    const action = reviewKeyAction(e, onButton);
    if (!action) return;
    const at = flat.findIndex((r) => r.run_id === sel);
    if (action === 'next' || action === 'prev') {
      const to = flat[Math.max(0, Math.min(flat.length - 1, at < 0 ? 0 : at + (action === 'next' ? 1 : -1)))]!;
      sel = to.run_id;
      const el = rowEl(to.run_id);
      el?.focus({ preventScroll: true });
      el?.scrollIntoView?.({ block: 'nearest' });
      if (data.drawer) openDrawer('run', to.run_id);
    } else if (action === 'open' && at >= 0) {
      openDrawer('run', sel!);
    } else if (action === 'good' && at >= 0 && isUnread(flat[at]!, marks, data.now) && !leaving[sel!]) {
      good(sel!);
    } else {
      return;
    }
    e.preventDefault();
  }

  onMount(() => {
    document.addEventListener('keydown', keydown);
    return () => document.removeEventListener('keydown', keydown);
  });

  const empty = $derived(feed.status === 'ready' && !flat.length);
</script>

<div class="t-pane" data-ap-review bind:this={host}>
  {#if feed.status === 'error'}
    <State kind="error" title={t('automations.simple.read_failed')} hint={feed.error} data-review-error>
      {#snippet actions()}<Button size="sm" data-review-retry onclick={() => void reloadFeed()}>{t('automations.simple.retry')}</Button>{/snippet}
    </State>
  {:else if feed.status !== 'ready'}
    <State kind="loading" title={t('automations.loading')} />
  {:else}
    <div class="t-feed">
      <div class="t-feedbar">
        <span class="pl-label">{t('automations.simple.review.label')}</span>
        <Segmented
          label={t('automations.simple.review.group_aria')}
          options={[
            { value: 'review', label: t('automations.simple.review.mode_review'), attrs: { 'data-mode': 'review' } },
            { value: 'all', label: t('automations.simple.review.mode_all'), attrs: { 'data-mode': 'all' } },
          ]}
          bind:value={() => mode, (next) => (mode = next as typeof mode)}
        />
        <span class="t-quiet" data-review-counts>{t('automations.simple.review.counts', { review: toReview, all: feed.total })}</span>
        <span class="t-sp"></span>
        <Button size="sm" data-markall disabled={toReview === 0} onclick={markAll}>{t('automations.simple.review.mark_all')}</Button>
      </div>
      {#if pressedId}
        <State
          inline
          title={`${t('automations.simple.review.showing')} ${t(pressedId === 'waiting_on_you' ? 'automations.simple.review.filter_needs' : 'automations.simple.review.filter_failed')} ${feed.total}`}
          data-review-filter
        >
          {#snippet actions()}<Button size="sm" data-clearfilter onclick={clearFilter}>{t('automations.simple.review.filter_clear')}</Button>{/snippet}
        </State>
      {/if}
      {#if empty}
        {#if pressedId}
          <State title={t('automations.simple.review.nomatch_title')} hint={t('automations.simple.review.nomatch_body')} data-review-empty="nomatch" />
        {:else if !feed.runs.length}
          <State title={t('automations.simple.review.none_title')} hint={t('automations.simple.review.none_body')} data-review-empty="none" />
        {:else}
          <State title={t('automations.simple.review.caught_title')} hint={t('automations.simple.review.caught_body')} data-review-empty="caught" />
        {/if}
      {/if}
      {#each days as day (day.key)}
        <div class="t-day"><span class="pl-label">{day.label}</span><span class="t-quiet">{day.runs.length}</span></div>
        {#each day.runs as run (run.run_id)}
          {@const lines = runLines(run, run.title ? '' : face(run, slotOf(run as FeedRow, lookup), { clock, tz: data.tz, now: data.now }).text)}
          <ReviewRow
            runId={run.run_id}
            status={run.status}
            name={run.automation_name || data.automations.find((a) => a.automation_id === run.automation_id)?.name || ''}
            clock={clock.hm12(runTime(run))}
            word={runWord(run)}
            title={lines.title}
            summary={lines.summary}
            reviewed={!isUnread(run, marks, data.now)}
            selected={sel === run.run_id}
            entering={!!entering[run.run_id]}
            leaving={!!leaving[run.run_id]}
            onOpen={open}
            onGood={good}
          />
        {/each}
      {/each}
      {#if feed.nextBefore !== null}
        <Button size="sm" data-older disabled={feed.loadingMore} onclick={() => void loadOlder(feedParams() ?? {})}>
          {t('automations.simple.review.older', { n: left })}
        </Button>
      {:else if flat.length}
        <div class="t-quiet f-keys f-end">{t('automations.simple.review.end')}</div>
      {/if}
      {#if flat.length}
        <div class="f-keys">
          <kbd>j</kbd><kbd>k</kbd> {t('automations.simple.review.key_walk')} <kbd>enter</kbd> {t('automations.simple.review.key_open')}
          <kbd>r</kbd> {t('automations.simple.review.key_good')} <kbd>esc</kbd> {t('automations.simple.review.key_close')}
        </div>
      {/if}
    </div>
  {/if}
</div>
