<!-- the reading pane -->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import '../ledger/ledger-chrome.css';
  import '../computers/computers.css';
  import '../pack-machines/pack-settings.css';
  import './roster.css';
  import { t } from '../i18n/index.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import SearchField from '../../opscenter/ui/SearchField.svelte';
  import ViewToggle from '../manager-frame/ViewToggle.svelte';
  import RosterFacet from './RosterFacet.svelte';
  import RankPanel, { type RankRow } from '../../opscenter/ui/RankPanel.svelte';
  import { computers, stopJoinPoll } from '../computers/computers-store.svelte';
  import { packMachines } from '../pack-machines/pack-machines-store.svelte';
  import { createFederationApi, readPackName } from '../hosts-page/federation-api';
  import { ageWords } from '../computers/computers-format';
  import { hosts, peers, nearby, discovered, refreshRoster, rosterActivity } from './roster-store.svelte';
  import { closePane, openAdd, openComputer, rosterUi, setSettings } from './roster-ui.svelte';
  import { buildRoster, countsOf, freeCpu, inFilter, LOOK_FILTERS, matches, PACK_FILTERS, sortRoster, unlinkedNearby, type FilterKey, type SortKey } from './roster-model';
  import { clock, startClock } from '../../opscenter/lib/frozen-clock.svelte';
  import RosterCard from './RosterCard.svelte';
  import ComputerPane from './ComputerPane.svelte';
  import AddPane from './AddPane.svelte';
  import SettingsPanel from './SettingsPanel.svelte';

  let nowMs = $state(Date.now());
  const stopClock = startClock();
  $effect(() => { void clock.now; nowMs = Date.now(); });
  let bodyEl = $state<HTMLElement | undefined>();
  let packName = $state<string | null>(null);
  let advertising = $state<boolean | null>(null);
  onMount(() => {
    if (rosterUi.settings === null) rosterUi.settings = (bodyEl?.clientWidth ?? 0) >= 860 && window.innerWidth >= 768;
    void refreshRoster();
    void readPackName().then((n) => { packName = n; }).catch(() => { packName = null; });
    void createFederationApi().settings().then((x) => { advertising = x.advertise; }).catch(() => { advertising = null; });
  });
  onDestroy(() => { stopClock(); stopJoinPoll(); });

  const list = $derived(buildRoster({ view: computers.data, machines: packMachines.data?.machines ?? [], hosts: hosts.data?.hosts ?? [], peers: Array.isArray(peers.data) ? peers.data : [] }));
  const counts = $derived(countsOf(list));
  const looks = $derived(LOOK_FILTERS.filter((k) => counts[k] > 0));
  const visible = $derived(sortRoster(list.filter((c) => inFilter(c, rosterUi.filter) && matches(c, rosterUi.q)), rosterUi.sort));
  const ghosts = $derived(unlinkedNearby(nearby(), list).filter((d) => rosterUi.q.trim() === '' || d.name.toLowerCase().includes(rosterUi.q.trim().toLowerCase())));
  const open = $derived(list.find((c) => c.id === rosterUi.openId) ?? null);
  const loaded = $derived(computers.data !== null && packMachines.data !== null);
  const failed = $derived(!loaded && (computers.status === 'error' || packMachines.status === 'error'));
  const jobs = $derived((computers.data?.add_jobs ?? []).filter((j) => j.state !== 'joined'));
  const alpha = $derived(list.find((c) => c.isAlpha) ?? null);
  const others = $derived(list.filter((c) => !c.isSelf && c.kind === 'pack'));
  const linked = $derived(others.filter((c) => c.dial === 'linked').length);
  const detailOpen = $derived(open !== null || rosterUi.mode === 'add');

  $effect(() => { if (LOOK_FILTERS.includes(rosterUi.filter) && loaded && counts[rosterUi.filter] === 0) rosterUi.filter = 'all'; });
  $effect(() => {
    if (!rosterUi.landSsh || !loaded) return;
    rosterUi.landSsh = false;
    rosterUi.filter = 'overssh';
    const first = sortRoster(list.filter((c) => inFilter(c, 'overssh')), rosterUi.sort)[0];
    if (first) openComputer(first.id, 'ssh');
  });

  const freeRows = $derived<RankRow[]>(list.map((c) => ({ c, f: freeCpu(c) })).filter((x) => x.f !== null).sort((a, b) => (b.f ?? 0) - (a.f ?? 0)).slice(0, 5)
    .map((x) => ({ id: x.c.id, name: x.c.name, tags: x.c.kind === 'ssh-only' ? [t('roster.census.ssh_host')] : [], metric: { value: String(x.f), unit: t('roster.census.free_of', { cores: x.c.machine?.snapshot?.load?.cores ?? '' }) } })));

  const sortOptions = $derived((['status', 'name', 'free', 'seen'] as const).map((k) => ({ value: k, label: t(`roster.sort.${k}`) })));
  function onKeydown(event: KeyboardEvent): void {
    const target = event.target as HTMLElement;
    if (event.key === 'Escape' && detailOpen && !target.closest('.oc-facet, .m1-sets')) { const was = rosterUi.openId; closePane(); if (was) bodyEl?.querySelector<HTMLElement>(`[data-computer-card="${was}"] .m1-name`)?.focus(); return; }
    if (!/^Arrow/.test(event.key) || !target.classList.contains('m1-name')) return;
    const names = [...(bodyEl?.querySelectorAll<HTMLElement>('.rs-scroll .m1-name') ?? [])];
    const at = names.indexOf(target);
    const next = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? at + 1 : at - 1;
    if (next >= 0 && next < names.length) { event.preventDefault(); names[next]?.focus(); }
  }
</script>

<svelte:window onkeydown={onKeydown} />
<div class="rs-screen pledger" data-roster>
  <div class="oc-page__bar rs-bar"><div class="oc-toolbar" role="search">
    <div class="oc-toolbar__search"><SearchField value={rosterUi.q} onInput={(v) => (rosterUi.q = v)} placeholder={t('roster.find.placeholder')} ariaLabel={t('roster.find.placeholder')} /></div>
    <div class="oc-toolbar__end">
      <RosterFacet label={t('roster.sort.label')} options={sortOptions} value={rosterUi.sort} onChange={(v) => (rosterUi.sort = v as SortKey)} />
      <ViewToggle view={rosterUi.view === 'list' ? 'list' : 'grid'} onView={(v) => (rosterUi.view = v === 'list' ? 'list' : 'cards')} {t} shelf />
    </div>
  </div></div>
  <div class="rs-body" bind:this={bodyEl} data-sets={rosterUi.settings ? '' : null}>
    <nav class="cat-rail" aria-label={t('roster.rail.label')}>
      <div class="cat-rail__group" role="radiogroup" aria-label={t('roster.rail.pack')}><span class="cat-rail__label">{t('roster.rail.pack')}</span>
        {#each PACK_FILTERS as key (key)}
          <button type="button" role="radio" class="cat-rail__row" aria-checked={rosterUi.filter === key && !rosterUi.mode} data-rail={key} onclick={() => { rosterUi.filter = key; rosterUi.mode = null; }}>
            <span class="cat-rail__name">{t(`roster.filter.${key}`)}</span><span class="cat-rail__count">{loaded ? counts[key] : ''}</span></button>
        {/each}
      </div>
      {#if looks.length > 0}
        <hr class="m1-rail-hr" />
        <div class="cat-rail__group" data-look="" role="radiogroup" aria-label={t('roster.rail.look')}><span class="cat-rail__label">{t('roster.rail.look')}</span>
          {#each looks as key (key)}
            <button type="button" role="radio" class="cat-rail__row" aria-checked={rosterUi.filter === key} data-rail={key} onclick={() => (rosterUi.filter = key)}>
              <span class="cat-rail__name">{t(`roster.look.${key}`)}</span><span class="cat-rail__count">{counts[key]}</span></button>
          {/each}
        </div>
      {/if}
    </nav>

    <div class="rs-scroll">
      <div class="cat-main m1-main">
        {#if failed}
          <div class="rs-state" role="alert"><p>{t('roster.err.title')}</p>
            <ul class="m1-reads">
              <li><span class="pp-st" data-shape="slash" data-tone="bad"><i class="pp-st__mark"></i><span class="pp-st__word">{t('roster.err.could_not')}</span></span> {computers.status === 'error' ? t('roster.err.computers') : t('roster.err.hosts')}
                <button type="button" class="oc-btn oc-btn--sm" aria-label={t('roster.err.retry_aria', { what: t('roster.err.computers') })} onclick={() => { void computers.refresh(true); void packMachines.refresh(true); }}>{t('roster.err.retry')}</button></li>
            </ul></div>
        {:else if !loaded}
          <p class="rs-state" role="status">{t('computers.loading')}</p>
        {:else}
          <div class="wz-census m1-census" class:m1-census--two={true}>
            <section class="oc-rank m1-census__pack" data-panel="pack">
              <header class="oc-rank__head"><h3 class="oc-rank__label">{t('roster.census.pack')}</h3>
                <button type="button" class="oc-btn oc-btn--sm oc-btn--ghost" onclick={() => setSettings(true)}>{t('roster.census.settings')}</button></header>
              <dl class="pp-facts">
                <dt class="m1-lead-k" role="img" aria-label={t('roster.census.leader')} title={t('roster.census.leader')}><Icon name="wolf" size={14} /></dt><dd>{alpha?.name ?? '-'}</dd>
                <dt>{t('roster.census.linked')}</dt><dd>{others.length ? t('roster.census.linked_of', { linked, total: others.length }) : t('roster.census.none')}</dd>
                <dt>{t('roster.census.name')}</dt><dd>{packName ?? t('roster.census.not_named')}</dd>
                <dt>{t('roster.census.advertising')}</dt><dd>{advertising === null ? '-' : advertising ? t('roster.census.on') : t('roster.census.off')}</dd>
              </dl>
            </section>
            <RankPanel label={t('roster.census.headroom')} rows={freeRows} columns={{ name: t('roster.census.col_computer'), metric: t('roster.census.col_free') }} notMeasured={t('roster.census.no_load')} empty={t('roster.census.no_load')} onSelect={(id) => openComputer(id, 'overview')} />
          </div>
          {#if rosterUi.filter === 'all' && ghosts.length > 0}
            <section class="m1-near" data-panel="near" aria-label={t('roster.sec.near')}>
              <div class="cat-sec"><span class="cat-sec__label">{t('roster.sec.near')}</span>
                <button type="button" class="oc-btn oc-btn--sm oc-btn--ghost" disabled={rosterActivity.busy !== null} onclick={() => void discovered.refresh(true)}>{t('hosts.fed.rescan')}</button>
                <span class="cat-sec__count">{t('roster.sec.near_count', { count: ghosts.length })}</span></div>
              <ul class="warez-grid m1-ghosts">
                {#each ghosts as d (d.fid)}
                  <li><article class="catalog-card m1-ghost" data-near={d.fid}>
                    <div class="catalog-card__head"><span class="catalog-card__name"><span class="oc-icon-tile m1-ghost__icon" aria-hidden="true">{d.name.charAt(0).toUpperCase()}</span><span class="m1-ghost__name">{d.name}</span></span>
                      <span class="catalog-card__slot"><button type="button" class="oc-btn oc-btn--sm oc-btn--confirm" aria-label={t('roster.near.link_aria', { name: d.name })} onclick={() => { rosterUi.route = 'older'; openAdd('older'); }}>{t('roster.near.link')}</button></span></div>
                    <div class="m1-brief m1-ghost__brief"><span class="pp-dim">{d.host}</span><span class="pp-dim">{t('roster.near.brief', { key: d.fid.slice(0, 8) })}</span>
                      <span class="m1-brief__st"><span class="pp-st" data-shape="tri" data-tone="warn"><i class="pp-st__mark" aria-hidden="true"></i><span class="pp-st__word">{t('roster.near.trust')}</span></span></span></div>
                  </article></li>
                {/each}
              </ul></section>
          {/if}
          <div class="cat-sec"><span class="cat-sec__label">{t('roster.sec.computers')}</span><span class="cat-sec__count">{t('roster.sec.computers_count', { shown: visible.length, total: list.length })}</span></div>
          {#if visible.length === 0 && jobs.length === 0}
            <div class="m1-empty"><span>{list.length === 0 ? t('roster.empty_all') : t('roster.empty_filter')}</span>
              <button type="button" class="oc-btn oc-btn--sm" onclick={() => { rosterUi.q = ''; rosterUi.filter = 'all'; }}>{t('roster.clear_filter')}</button></div>
          {:else if rosterUi.view === 'list'}
            <ul class="m1-rows">{#each visible as c (c.id)}<RosterCard {c} list open={rosterUi.openId === c.id && !rosterUi.mode} onOpen={(id) => openComputer(id)} {nowMs} />{/each}</ul>
          {:else}
            <ul class="warez-grid m1-grid">
              {#if rosterUi.filter === 'all' && rosterUi.q === ''}
                {#each jobs as job (job.id)}
                  <li><article class="catalog-card m1-card" data-pending={job.id} data-off="">
                    <header class="m1-top"><span class="m1-top__id"><span class="oc-icon-tile" aria-hidden="true">{(job.target.split('@')[1] ?? job.target).charAt(0).toUpperCase()}</span><span class="catalog-card__open m1-name">{job.target.split('@')[1] ?? job.target}</span></span></header>
                    <div class="m1-brief"><span class="pp-dim">{t('roster.adding.installing', { target: job.target })}</span>
                      <span class="m1-brief__st"><span class="pp-st" data-shape="hollow" data-tone={job.error ? 'bad' : 'ok'}><i class="pp-st__mark"></i><span class="pp-st__word">{job.error ? t('roster.adding.stopped') : t('roster.adding.label')}</span></span></span></div>
                  </article></li>
                {/each}
              {/if}
              {#each visible as c (c.id)}<RosterCard {c} open={rosterUi.openId === c.id && !rosterUi.mode} onOpen={(id) => openComputer(id)} {nowMs} />{/each}
            </ul>
          {/if}
          {#if list.length === 1 && list[0]?.isSelf && rosterUi.q === ''}
            <div class="m1-empty"><span>{t('roster.only_self')}</span><button type="button" class="oc-btn oc-btn--sm oc-btn--confirm" onclick={() => openAdd()}>{t('roster.toolbar.add')}</button></div>
          {/if}
        {/if}
      </div>
    </div>

    {#if detailOpen}
      <div class="rs-detail m1-pane" data-panel="detail">
        {#if rosterUi.mode === 'add'}<AddPane onClose={closePane} />
        {:else if open}<ComputerPane c={open} computers={list} {nowMs} onClose={closePane} />{/if}
      </div>
    {/if}
    {#if rosterUi.settings}<SettingsPanel onClose={() => setSettings(false)} {nowMs} />{/if}
  </div>
</div>
