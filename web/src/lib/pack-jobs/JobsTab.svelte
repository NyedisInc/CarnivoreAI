
<script lang="ts">
  import '../ledger/ledger-chrome.css';
  import '../pack-machines/pack-machines.css';
  import '../pack-transport/pack-transport.css';
  import './pack-activity.css';
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import { openModal } from '../modal';
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import Fold from '../base/Fold.svelte';
  import List from '../base/List.svelte';
  import Segmented from '../base/Segmented.svelte';
  import Select from '../base/Select.svelte';
  import StatTile from '../base/StatTile.svelte';
  import Toolbar from '../base/Toolbar.svelte';
  import { openSession } from '../../plugins/sdk/sessions.svelte';
  import { activityApi, type PackActivityApi, type PackActivityItem, type PackActivityResponse } from './activity-api';
  import ActivityRow from './ActivityRow.svelte';
  import type { JobView } from './jobs-api';
  import { isLive } from './jobs-format';
  import JobsNumbers from './JobsNumbers.svelte';
  import PackComputerStrip from './PackComputerStrip.svelte';
  import StopJobDialog from './StopJobDialog.svelte';
  import { jobsStore, type JobsDelta, type JobsStore } from './jobs-store.svelte';

  interface Props {
    store?: JobsStore;
    activity?: PackActivityApi;
    subscribe?: (handler: (frame: JobsDelta) => void) => (() => void) | null;
    delayMs?: number;
  }
  const { store = jobsStore, activity = activityApi, subscribe = pageSubscribe, delayMs = 10000 }: Props = $props();

  interface Listing {
    rows?(name: string): Array<{ session_uuid?: string | null; tmux_session?: string | null; session?: { id?: string } }> | null;
    onChange?(fn: (names: string[]) => void): () => void;
  }
  const listing = (): Listing | undefined => (globalThis as { ListingPush?: Listing }).ListingPush;

  function pageSubscribe(handler: (frame: JobsDelta) => void): (() => void) | null {
    const events = (globalThis as { AppEvents?: { subscribe?(h: (f: JobsDelta) => void): () => void } }).AppEvents;
    return events?.subscribe?.((frame) => { if (frame?.type === 'pack_jobs.delta') handler(frame); }) ?? null;
  }

  let listingTick = $state(0);
  let data = $state<PackActivityResponse | null>(null);
  let loadingActivity = $state(false);
  let activityError = $state<string | null>(null);

  let scope = $state<'live' | 'all'>('all');
  let kindFilter = $state<'all' | 'agents' | 'commands'>('all');
  let computerFilter = $state<string>('');
  let days = $state<string>('7');
  let query = $state<string>('');

  const daysNum = $derived(Math.max(1, Number(days) || 7));

  async function loadActivity(windowDays = daysNum): Promise<void> {
    loadingActivity = true;
    try {
      data = await activity.read({ days: windowDays, limit: 300, includePeers: true });
      activityError = null;
    } catch (failure) {
      activityError = nonEmptyErrorMessageOr(failure, t('pack.activity.error.failed'));
    } finally {
      loadingActivity = false;
    }
  }

  function findListingRow(uuid: string | null | undefined) {
    void listingTick;
    if (!uuid) return undefined;
    return listing()?.rows?.('list')?.find((row) => row.session_uuid === uuid);
  }

  function openByUuid(uuid: string): void {
    const row = findListingRow(uuid);
    if (row?.session?.id && row.tmux_session) void openSession(row.session.id, row.tmux_session);
  }

  function askStop(job: JobView): void {
    void openModal(StopJobDialog, { job, store });
  }

  function jobViewFor(item: PackActivityItem): JobView | undefined {
    return item.job_id ? store.rows[item.job_id] : undefined;
  }

  const allItems = $derived<PackActivityItem[]>(data?.items ?? []);
  const filteredItems = $derived.by(() => {
    const q = query.trim().toLowerCase();
    const caller = store.caller;
    return allItems.filter((item) => {
      if (scope === 'live' && !item.live) return false;
      if (kindFilter === 'agents' && item.item_type === 'command') return false;
      if (kindFilter === 'commands' && item.item_type !== 'command') return false;
      if (computerFilter && item.computer_id !== computerFilter) return false;
      if (caller && item.started_by.session_uuid !== caller && item.session_uuid !== caller) return false;
      if (q) {
        const hay = `${item.title} ${item.project} ${item.computer_label} ${item.source_computer_label ?? ''} ${item.started_by.label} ${item.reason ?? ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  });

  const liveItems = $derived(filteredItems.filter((i) => i.live));
  const historyItems = $derived(filteredItems.filter((i) => !i.live));
  const totalLiveCount = $derived(allItems.filter((i) => i.live).length);

  const scopeOptions = $derived([
    { value: 'live', label: t('pack.activity.scope.live', { count: String(totalLiveCount) }) },
    { value: 'all', label: t('pack.activity.scope.all', { count: String(allItems.length) }) },
  ]);
  const kindOptions = $derived([
    { value: 'all', label: t('pack.activity.kind_filter.all') },
    { value: 'agents', label: t('pack.activity.kind_filter.agents') },
    { value: 'commands', label: t('pack.activity.kind_filter.commands') },
  ]);
  const windowOptions = $derived([
    { value: '1', label: t('pack.activity.window.1') },
    { value: '7', label: t('pack.activity.window.7') },
    { value: '30', label: t('pack.activity.window.30') },
  ]);

  const agg = $derived(data?.fleet_aggregate ?? null);
  const fanoutText = $derived.by(() => {
    const f = agg?.peer_fanout;
    if (!f || f.queried === 0) return '';
    return f.skipped > 0
      ? t('pack.activity.fanout.partial', { ok: String(f.ok), total: String(f.queried) })
      : t('pack.activity.fanout.ok', { ok: String(f.ok) });
  });
  const offloadPct = $derived(
    data?.summary?.r3_remote_share !== null && data?.summary?.r3_remote_share !== undefined
      ? `${Math.round(data.summary.r3_remote_share * 100)}%`
      : '-',
  );
  const cpuRamFigure = $derived(
    agg?.fleet_cpu_pct !== null && agg?.fleet_cpu_pct !== undefined
      ? `${Math.round(agg.fleet_cpu_pct)}% / ${agg.fleet_ram_pct !== null && agg.fleet_ram_pct !== undefined ? Math.round(agg.fleet_ram_pct) : '-'}%`
      : '-',
  );
  const overheadFigure = $derived(
    data?.efficiency?.p50_overhead_s !== null && data?.efficiency?.p50_overhead_s !== undefined
      ? `${data.efficiency.p50_overhead_s}s`
      : '-',
  );
  const hasFilters = $derived(Boolean(computerFilter || query.trim() || kindFilter !== 'all' || store.caller));

  function clearFilters(): void {
    computerFilter = '';
    query = '';
    kindFilter = 'all';
    store.setCaller(null);
  }

  function onWindowChange(): void {
    void loadActivity(daysNum);
  }

  onMount(() => {
    let wait: ReturnType<typeof setTimeout> | null = null;
    store.setVisible(true);
    void loadActivity(daysNum);
    const offListing = listing()?.onChange?.((names) => {
      if (names.includes('list') || names.includes('$live')) listingTick += 1;
    });
    const offFeed = subscribe((frame) => {
      if (!frame.job || isLive(frame.job)) return;
      if (wait) clearTimeout(wait);
      wait = setTimeout(() => {
        wait = null;
        void loadActivity(daysNum);
      }, delayMs);
    });
    return () => {
      if (wait) clearTimeout(wait);
      store.setVisible(false);
      offListing?.();
      offFeed?.();
    };
  });
</script>

<section class="pm-panel pl-panel pledger" aria-labelledby="pk-jobs-title" data-pack-jobs>
  <div class="pl-titlebar">
    <h2 class="pl-title" id="pk-jobs-title">{t('pack.activity.title')}</h2>
    <div class="pa-head-actions">
      {#if fanoutText}
        <span class="pa-fanout" data-activity="fanout">{fanoutText}</span>
      {/if}
      <Button size="sm" disabled={loadingActivity} data-activity="refresh" onclick={() => void loadActivity(daysNum)}>
        {loadingActivity ? t('pack.activity.refreshing') : t('pack.activity.refresh')}
      </Button>
    </div>
  </div>

  <div class="pm-body pa-deck">
    {#if activityError || store.error}
      <p class="pt-error" role="alert" data-jobs="error">{activityError || store.error}</p>
    {/if}

    
    {#if agg}
      <div class="pa-kpis" data-activity="kpis">
        <StatTile
          size="compact"
          mode="flat"
          label={t('pack.activity.kpi.running')}
          figure={String(agg.live_agents_total + agg.live_jobs_total)}
          sub={t('pack.activity.kpi.running_sub', { agents: String(agg.live_agents_total), jobs: String(agg.live_jobs_total) })}
          tone="--oc-green"
        />
        <StatTile
          size="compact"
          mode="flat"
          label={t('pack.activity.kpi.fleet_load')}
          figure={cpuRamFigure}
          sub={t('pack.activity.kpi.fleet_load_sub', {
            cores: String(Math.round((agg.usable_free_cores ?? 0) * 10) / 10),
            ram: String(Math.round((agg.usable_free_ram_gb ?? 0) * 10) / 10),
          })}
          tone="--oc-cyan"
        />
        <StatTile
          size="compact"
          mode="flat"
          label={t('pack.activity.kpi.offloaded', { days: String(daysNum) })}
          figure={offloadPct}
          sub={t('pack.activity.kpi.history_sub', { count: String(agg.history_total) })}
          tone="--oc-orange"
        />
        <StatTile
          size="compact"
          mode="flat"
          label={t('pack.activity.kpi.overhead')}
          figure={overheadFigure}
          sub={t('pack.activity.kpi.waste_sub', { waste: String(data?.utilization_history?.idle_while_peer_pegged_minutes ?? 0) })}
          tone="--oc-yellow"
        />
      </div>
    {/if}

    
    {#if data && data.computers.length > 0}
      <PackComputerStrip
        computers={data.computers}
        selected={computerFilter}
        days={daysNum}
        onSelect={(id) => { computerFilter = id; }}
      />
    {/if}

    
    <Toolbar band wrap label={t('pack.activity.toolbar.label')} data-jobs="filters">
      {#snippet search()}
        <Field
          variant="search"
          label={t('pack.activity.search.label')}
          placeholder={t('pack.activity.search.placeholder')}
          clearLabel={t('pack.activity.search.clear')}
          bind:value={query}
        />
      {/snippet}
      {#snippet filters()}
        <Segmented label={t('pack.jobs.filter.label')} options={scopeOptions} value={scope} onchange={(v) => { scope = v === 'live' ? 'live' : 'all'; }} />
        <Segmented label={t('pack.activity.kind_filter.label')} options={kindOptions} value={kindFilter} onchange={(v) => { kindFilter = (v === 'agents' || v === 'commands') ? v : 'all'; }} />
        <Select size="sm" aria-label={t('pack.activity.filter.window')} options={windowOptions} bind:value={days} onchange={onWindowChange} />
      {/snippet}
      {#snippet end()}
        {#if hasFilters}
          <Button size="sm" data-activity="clear-filters" onclick={clearFilters}>{t('pack.activity.filter.clear')}</Button>
        {/if}
      {/snippet}
      {#snippet below()}
        {#if store.caller}
          <div class="pa-filter-chips">
            <Button size="sm" data-jobs="caller-chip" onclick={() => store.setCaller(null)}>{t('pack.jobs.caller_chip')}</Button>
          </div>
        {/if}
      {/snippet}
    </Toolbar>

    
    <div class="pa-section" data-activity="live-section">
      <div class="pa-section__head">
        <h3 class="pa-section__title">{t('pack.activity.section.live')}</h3>
        <span class="pa-section__count">{liveItems.length}</span>
      </div>
      {#if liveItems.length === 0}
        <p class="pt-note" data-activity="live-empty">
          {loadingActivity && !data ? t('pack.jobs.loading') : t('pack.activity.empty.live')}
        </p>
      {:else}
        <List label={t('pack.activity.section.live')} density="roomy" data-activity="live-list">
          {#snippet children()}
            {#each liveItems as item (item.id)}
              <ActivityRow
                {item}
                jobView={jobViewFor(item)}
                canOpenSession={!!findListingRow(item.session_uuid)}
                canOpenStarter={!!findListingRow(item.started_by.session_uuid)}
                onOpenSession={openByUuid}
                onStopJob={askStop}
                onFilterComputer={(id) => { computerFilter = id; }}
              />
            {/each}
          {/snippet}
        </List>
      {/if}
    </div>

    
    {#if scope === 'all'}
      <div class="pa-section" data-activity="history-section">
        <div class="pa-section__head">
          <h3 class="pa-section__title">{t('pack.activity.section.history', { days: String(daysNum) })}</h3>
          <span class="pa-section__count">{historyItems.length}</span>
        </div>
        {#if historyItems.length === 0}
          <p class="pt-note" data-activity="history-empty">
            {loadingActivity && !data ? t('pack.jobs.loading') : t('pack.activity.empty.history')}
          </p>
        {:else}
          <List label={t('pack.activity.section.history', { days: String(daysNum) })} density="roomy" data-activity="history-list">
            {#snippet children()}
              {#each historyItems as item (item.id)}
                <ActivityRow
                  {item}
                  jobView={jobViewFor(item)}
                  canOpenSession={!!findListingRow(item.session_uuid)}
                  canOpenStarter={!!findListingRow(item.started_by.session_uuid)}
                  onOpenSession={openByUuid}
                  onStopJob={askStop}
                  onFilterComputer={(id) => { computerFilter = id; }}
                />
              {/each}
            {/snippet}
          </List>
        {/if}
      </div>
    {/if}

    
    <Fold label={t('pack.activity.metrics_fold')}>
      <JobsNumbers />
    </Fold>
  </div>
</section>
