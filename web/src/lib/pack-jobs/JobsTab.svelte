
<script lang="ts">
  import '../ledger/ledger-chrome.css';
  import '../pack-machines/pack-machines.css';
  import '../pack-transport/pack-transport.css';
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { openModal } from '../modal';
  import Button from '../base/Button.svelte';
  import List from '../base/List.svelte';
  import Segmented from '../base/Segmented.svelte';
  import { openSession } from '../../plugins/sdk/sessions.svelte';
  import type { JobView } from './jobs-api';
  import JobRow from './JobRow.svelte';
  import JobsNumbers from './JobsNumbers.svelte';
  import StopJobDialog from './StopJobDialog.svelte';
  import { jobsStore, type JobsStore } from './jobs-store.svelte';

  const { store = jobsStore }: { store?: JobsStore } = $props();

  interface Listing {
    rows?(name: string): Array<{ session_uuid?: string | null; tmux_session?: string | null; session?: { id?: string } }> | null;
    onChange?(fn: (names: string[]) => void): () => void;
  }
  const listing = (): Listing | undefined => (globalThis as { ListingPush?: Listing }).ListingPush;

  let listingTick = $state(0);
  const mine = $derived(store.shown.filter((j) => j.side === 'caller'));
  const others = $derived(store.shown.filter((j) => j.side === 'host'));
  const choices = $derived([
    { value: 'live', label: t('pack.jobs.filter.live') },
    { value: 'all', label: t('pack.jobs.filter.all') },
  ]);

  function workerRow(job: JobView) {
    void listingTick;
    const want = job.worker_listing_uuid;
    return want ? listing()?.rows?.('list')?.find((row) => row.session_uuid === want) : undefined;
  }

  function openWorker(job: JobView): void {
    const row = workerRow(job);
    if (row?.session?.id && row.tmux_session) void openSession(row.session.id, row.tmux_session);
  }

  function askStop(job: JobView): void {
    void openModal(StopJobDialog, { job, store });
  }

  onMount(() => {
    store.setVisible(true);
    const off = listing()?.onChange?.((names) => { if (names.includes('list') || names.includes('$live')) listingTick += 1; });
    return () => {
      store.setVisible(false);
      off?.();
    };
  });
</script>

<section class="pm-panel pl-panel pledger" aria-labelledby="pk-jobs-title" data-pack-jobs>
  <div class="pl-titlebar">
    <h2 class="pl-title" id="pk-jobs-title">{t('pack.jobs.title')}</h2>
  </div>
  <div class="pm-body pk-col">
    <div class="pt-row" data-jobs="filters">
      <Segmented label={t('pack.jobs.filter.label')} options={choices} value={store.filter} onchange={(v) => store.setFilter(v === 'all' ? 'all' : 'live')} />
      {#if store.caller}
        <Button variant="quiet" size="sm" data-jobs="caller-chip" onclick={() => store.setCaller(null)}>{t('pack.jobs.caller_chip')}</Button>
      {/if}
    </div>
    <JobsNumbers />
    {#if store.error}<p class="pt-error" role="alert" data-jobs="error">{store.error}</p>{/if}
    {#if mine.length === 0 && others.length === 0}
      <p class="pt-note" data-jobs="empty">{t(store.loading ? 'pack.jobs.loading' : store.filter === 'live' ? 'pack.jobs.empty_live' : 'pack.jobs.empty')}</p>
    {/if}
    {#if mine.length > 0}
      <List label={t('pack.jobs.title')} density="roomy" data-jobs="group-mine">
        {#snippet children()}
          {#each mine as job (job.id)}
            <JobRow {job} canOpenWorker={!!workerRow(job)} onStop={askStop} onOpenWorker={openWorker} />
          {/each}
        {/snippet}
      </List>
    {/if}
    {#if others.length > 0}
      <h3 class="pl-label" data-jobs="others-title">{t('pack.jobs.others')}</h3>
      <List label={t('pack.jobs.others')} density="roomy" data-jobs="group-others">
        {#snippet children()}
          {#each others as job (job.id)}<JobRow {job} />{/each}
        {/snippet}
      </List>
    {/if}
    {#if store.canMore}
      <div class="pt-row">
        <Button variant="quiet" size="sm" data-jobs="more" onclick={() => void store.loadMore()}>{t('pack.jobs.more')}</Button>
      </div>
    {/if}
  </div>
</section>
