
<script lang="ts">
  import { untrack } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import State from '../../base/State.svelte';
  import { changed, infoOf, foldText, type FeedEntry, type FeedRow } from '../logic/feed';
  import { bytesWords, countWords, feedTookWords, triggerWord, runTime, type Clock } from '../logic/words';
  import { dayChanged, rowChanges, type FeedModel, type Seen } from './feed-model';
  import FeedRow_ from './FeedRow.svelte';

  type Props = {
    model: FeedModel;
    clock: Clock;
    selectedRunId: string | null;
    expanded: Record<string, boolean>;
    failed: boolean;
    failedText: string;
    anyFilter: boolean;
    total: number;
    left: number;
    hasMore: boolean;
    loadingMore: boolean;
    nameOf: (run: FeedRow) => string;
    whereOf: (run: FeedRow) => string;
    retryMaxOf: (run: FeedRow) => number;
    onPick: (rowKey: string) => void;
    onLoadOlder: () => void;
    onRetry: () => void;
    onClear: () => void;
    scrollTick: number;
  };
  let { model, clock, selectedRunId, expanded, failed, failedText, anyFilter, total, left, hasMore, loadingMore, nameOf, whereOf, retryMaxOf, onPick, onLoadOlder, onRetry, onClear, scrollTick }: Props = $props();

  let listEl: HTMLDivElement | undefined = $state();
  let refitTick = $state(0);
  let seen: Seen | null = null;
  let lastWalk = 0;
  let entering = $state<Record<string, true>>({});
  let ticked = $state<Record<string, true>>({});

  $effect(() => {
    const shown = model.pg.shown;
    untrack(() => {
      const next = rowChanges(seen, shown);
      seen = next.seen;
      entering = next.entering;
      ticked = next.ticked;
    });
  });

  $effect(() => {
    if (!listEl || typeof ResizeObserver === 'undefined') return;
    let width = 0;
    const watch = new ResizeObserver(() => {
      const w = listEl?.clientWidth ?? 0;
      if (w !== width) {
        width = w;
        refitTick += 1;
      }
    });
    watch.observe(listEl);
    return () => watch.disconnect();
  });

  $effect(() => {
    const walked = scrollTick;
    void selectedRunId;
    void model.rows;
    if (!listEl) return;
    const idx = model.rows.findIndex((x) => holds(x.key, x.kind, x.entry));
    const el = idx < 0 ? null : (document.getElementById(`e-${model.rows[idx]!.key}`) as HTMLElement | null);
    if (!el) return;
    listEl.setAttribute('aria-activedescendant', el.id);
    if (walked === lastWalk) return;
    lastWalk = walked;
    const lr = listEl.getBoundingClientRect();
    const er = el.getBoundingClientRect();
    if (er.top < lr.top + 30 || er.bottom > lr.bottom) el.scrollIntoView?.({ block: 'nearest' });
  });

  function holds(key: string, kind: 'run' | 'fold' | 'member', entry: FeedEntry): boolean {
    if (!selectedRunId) return false;
    if (kind === 'member') return key === `m:${selectedRunId}`;
    if (kind === 'run') return entry.run.run_id === selectedRunId;
    return !expanded[key] && entry.members.some((m) => m.run_id === selectedRunId);
  }

  function faceTitle(text: string, rule: string, count: number): string {
    return `${text} (${rule.replace(/_/g, ' ')}${count > 1 ? `, ${count} runs` : ''})`;
  }
</script>

<div
  class="ap-fd-list"
  id="ap-fd-list"
  role="listbox"
  tabindex="0"
  aria-label={t('automations.page.feed.list.aria')}
  bind:this={listEl}
  data-feed-list
>
  {#if failed}
    <State kind="error" title={failedText} data-feed-error>
      {#snippet actions()}<Button size="sm" data-act="retry-list" onclick={onRetry}>{t('automations.page.try_again')}</Button>{/snippet}
    </State>
  {:else if !model.pg.shown.length}
    <State title={anyFilter || total > 0 ? t('automations.page.feed.no_match') : t('automations.page.feed.none')} data-feed-empty>
      {#snippet actions()}
        {#if anyFilter}<Button size="sm" data-act="clear" onclick={onClear}>{t('automations.page.clear_filters')}</Button>{/if}
      {/snippet}
    </State>
  {:else}
    {#each model.pg.days as day (day.key)}
      {@const dc = dayChanged(day, model.info)}
      <div class="ap-fd-day" role="presentation">
        <span class="pl-label">{day.label}</span>
        <span class="ap-fd-dc ap-num">{countWords('automations.page.count.run', day.runs)}{dc ? t('automations.page.feed.day_changed', { n: dc }) : ''}</span>
      </div>
      {#each day.entries as e (e.key)}
        {@const r = e.run}
        {@const f = model.faceOf(r)}
        {@const kind = e.type === 'fold' ? 'fold' : 'run'}
        {@const text = e.type === 'fold' ? foldText(e, f.text, clock) : f.text}
        {@const info = infoOf(model.info, r)}
        <FeedRow_
          {kind}
          rowKey={e.key}
          runId={r.run_id}
          status={r.status}
          name={nameOf(r)}
          where={whereOf(r)}
          time={clock.hms24(runTime(r))}
          trigger={triggerWord(r, retryMaxOf(r))}
          faceText={text}
          faceTitle={faceTitle(text, f.rule, e.type === 'fold' ? e.members.length : 1)}
          took={feedTookWords(r) ?? ''}
          size={r.report_bytes ? bytesWords(r.report_bytes) : ''}
          selected={holds(e.key, kind, e)}
          unread={e.type === 'fold' ? e.members.some(model.unread) : model.unread(r)}
          changed={e.type === 'run' && changed(model.info, r)}
          same={info.same}
          first={info.first}
          expanded={!!expanded[e.key]}
          entering={!!entering[e.key]}
          ticked={!!ticked[e.key]}
          {refitTick}
          {onPick}
        />
        {#if e.type === 'fold' && expanded[e.key]}
          <div class="ap-fd-ms">
            {#each e.members as m (m.run_id)}
              {@const mf = model.faceOf(m)}
              <FeedRow_
                kind="member"
                rowKey={`m:${m.run_id}`}
                runId={m.run_id}
                status={m.status}
                name={`#${(m as FeedRow & { number?: number }).number ?? ''}`}
                where={whereOf(m)}
                time={clock.hms24(runTime(m))}
                trigger=""
                faceText={mf.text}
                faceTitle={faceTitle(mf.text, mf.rule, 1)}
                took={feedTookWords(m) ?? ''}
                size={m.report_bytes ? bytesWords(m.report_bytes) : ''}
                selected={holds(`m:${m.run_id}`, 'member', e)}
                unread={model.unread(m)}
                changed={false}
                same={false}
                first={false}
                expanded={false}
                entering={false}
                ticked={false}
                {refitTick}
                {onPick}
              />
            {/each}
          </div>
        {/if}
      {/each}
    {/each}
    {#if hasMore}
      <div class="ap-fd-more">
        <Button size="sm" data-act="load-older" disabled={loadingMore} onclick={onLoadOlder}>{t('automations.page.feed.load_older')}</Button>
        <span class="ap-num">{t('automations.page.feed.more', { n: left })}</span>
      </div>
    {:else}
      <div class="ap-fd-end">{t('automations.page.feed.end', { n: total })}</div>
    {/if}
  {/if}
</div>
