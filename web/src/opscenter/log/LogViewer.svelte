<script lang="ts">
  import { onDestroy } from 'svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { ApiLogSource } from './api-source';
  import { RecordBuffer } from './buffer';
  import { compile, emptyFilter, sourcesOf, toggleField, type LogFilter } from './filter';
  import { copyText, downloadJsonl, recordLine } from './export';
  import { readLevels, writeLevels } from './log-levels';
  import { msUntilReread } from './level-expiry';
  import Button from '../../lib/base/Button.svelte';
  import LogList from './LogList.svelte';
  import LogToolbar from './LogToolbar.svelte';
  import type { LevelState, LogPage, LogRecord, LogSource } from './types';

  interface Props {
    source?: LogSource;
  }

  const { source }: Props = $props();

  const FLUSH_FALLBACK_MS = 250;

  // svelte-ignore state_referenced_locally
  const from: LogSource = source ?? new ApiLogSource();
  const buffer = new RecordBuffer();
  let version = $state(0);
  let view = $state<'loading' | 'unknown' | 'ready'>('loading');
  let filter = $state<LogFilter>(emptyFilter(readLevels()));
  let expanded = $state.raw<Set<string>>(new Set());
  let following = $state(true);
  let unseen = $state(0);
  let before = $state<string | null>(null);
  let olderBusy = $state(false);
  let notice = $state<'' | 'gap' | 'reset'>('');
  let flash = $state('');
  let level = $state<LevelState | null>(null);
  let levelBusy = $state(false);

  const compiled = $derived(compile(filter));
  const records = $derived.by(() => {
    void version;
    return compiled.empty ? [...buffer.records] : buffer.records.filter(compiled.match);
  });
  const sources = $derived.by(() => {
    void version;
    return sourcesOf(buffer.records);
  });

  let pending: LogPage[] = [];
  let frame = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let first = true;
  let generation = 0;

  function flush(): void {
    if (frame) cancelAnimationFrame(frame);
    if (timer !== undefined) clearTimeout(timer);
    frame = 0;
    timer = undefined;
    const pages = pending;
    pending = [];
    for (const got of pages) {
      if (got.reset) {
        buffer.clear();
        generation += 1;
        expanded = new Set();
        notice = 'reset';
      } else if (got.gap) {
        notice = 'gap';
      }
      if (first || got.reset) before = got.before;
      first = false;
      const added = buffer.append(got.records);
      if (!following && added > 0) unseen += got.records.slice(-added).filter(compiled.match).length;
    }
    view = 'ready';
    version += 1;
  }

  function onBatch(got: LogPage): void {
    pending.push(got);
    if (frame || timer !== undefined) return;
    if (typeof requestAnimationFrame === 'function') frame = requestAnimationFrame(flush);
    timer = setTimeout(flush, FLUSH_FALLBACK_MS);
  }

  const stop = from.subscribe(onBatch, () => {
    if (view === 'loading') view = 'unknown';
  });
  void from.readLevel().then((state) => (level = state), () => (level = null));
  $effect(() => {
    const wait = level?.expires_at ? msUntilReread(level.expires_at) : null;
    if (wait === null) return;
    const timer = setTimeout(() => void from.readLevel().then((state) => (level = state), () => (level = null)), wait);
    return () => clearTimeout(timer);
  });
  onDestroy(() => {
    stop();
    if (frame) cancelAnimationFrame(frame);
    if (timer !== undefined) clearTimeout(timer);
  });

  function setFilter(next: LogFilter): void {
    if (next.levels !== filter.levels) writeLevels(next.levels);
    filter = next;
  }

  function setFollowing(next: boolean): void {
    following = next;
    if (next) unseen = 0;
  }

  async function loadOlder(): Promise<void> {
    if (!before || olderBusy) return;
    olderBusy = true;
    const asked = generation;
    try {
      const got = await from.backfill(before);
      if (asked !== generation) return;
      buffer.prepend(got.records);
      before = got.before;
      version += 1;
    } catch {
      flash = t('opscenter.log.older_failed');
    } finally {
      olderBusy = false;
    }
  }

  async function setLevel(next: string | null): Promise<void> {
    levelBusy = true;
    try {
      level = await from.setLevel(next);
    } catch {
      flash = t('opscenter.log.server_level.failed');
    } finally {
      levelBusy = false;
    }
  }

  async function copy(record: LogRecord): Promise<void> {
    flash = t((await copyText(recordLine(record))) ? 'opscenter.log.copied' : 'opscenter.log.copy_failed');
  }

  function toggleExpand(id: string): void {
    const next = new Set(expanded);
    if (!next.delete(id)) next.add(id);
    expanded = next;
  }

  function clearView(): void {
    buffer.clear();
    generation += 1;
    expanded = new Set();
    unseen = 0;
    notice = '';
    flash = '';
    version += 1;
  }
</script>

<div class="oc-rc oc-lv" data-log-monitor data-view={view}>
  <LogToolbar {filter} {sources} patternError={compiled.error} {level} {levelBusy} onFilter={setFilter} onLevel={(next) => void setLevel(next)}
    onExport={() => downloadJsonl(records)} onClear={clearView} />
  <div class="oc-lv-status" role="status" data-log-status>
    {#if before}
      <Button size="sm" variant="quiet" disabled={olderBusy} onclick={() => void loadOlder()} data-log-older>
        {t(olderBusy ? 'opscenter.log.older.loading' : 'opscenter.log.older')}</Button>
    {/if}
    <span class="oc-lv-count">{t('opscenter.log.count', { shown: records.length, held: buffer.records.length })}</span>
    {#if buffer.dropped}<span class="oc-lv-warn" data-log-dropped>{t('opscenter.log.dropped', { count: buffer.dropped })}</span>{/if}
    {#if buffer.refused}<span class="oc-lv-warn" data-log-refused>{t('opscenter.log.refused')}</span>{/if}
    {#if notice}<span class="oc-lv-warn" data-log-notice={notice}>{t(`opscenter.log.${notice}`)}</span>{/if}
    {#if flash}<span class="oc-lv-flash">{flash}</span>{/if}
    <span class="oc-lv-live" data-following={following ? '' : undefined}>{t(following ? 'opscenter.log.live' : 'opscenter.log.paused')}</span>
  </div>
  {#if view === 'loading'}
    <p class="oc-rc-notice" role="status">{t('opscenter.log.loading')}</p>
  {:else if view === 'unknown'}
    <p class="oc-rc-notice" data-tone="bad" role="status">{t('opscenter.log.unknown')}</p>
  {:else if filter.levels.length === 0}
    <p class="oc-rc-notice" role="status" data-log-none>{t('opscenter.log.no_levels')}</p>
  {:else if records.length === 0}
    <p class="oc-rc-notice" role="status" data-log-none>{t(buffer.records.length ? 'opscenter.log.no_match' : 'opscenter.log.empty')}</p>
  {/if}
  <LogList {records} {expanded} {following} {unseen} onFollow={setFollowing} onExpand={toggleExpand}
    onField={(key, value, exclude) => setFilter(toggleField(filter, key, value, exclude))} onCopy={(record) => void copy(record)} />
</div>
