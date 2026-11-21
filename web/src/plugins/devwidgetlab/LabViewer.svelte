<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { openTabPopout, t } from '../sdk';
  import { Button, IconButton, Segmented } from '../sdk/ui';
  import { labWidgets, type FrameReport, type LabHost, type SidebarView } from '../sdk/widget-lab';
  import { activeThemeId } from '../sdk/themes';
  import { fitTableState } from './lab-api';
  import { LabLink } from './lab-channel.svelte';
  import { frameScale, watchWidth, PHONE_MAX_PX } from './fit-scale';
  import { widgetVerdict, type FitTable as FitTableData } from './lab-model';
  import { appliedRoutes, bandSize, FALLBACK_THEME, type DrawerDock, type FrameRef } from './lab-selection';
  import CaptureResults from './CaptureResults.svelte';
  import DraftCompare from './DraftCompare.svelte';
  import FitTable from './FitTable.svelte';
  import HostBand from './HostBand.svelte';
  import './lab.css';

  const widgets = labWidgets();
  const link = new LabLink('viewer', widgets, activeThemeId() ?? FALLBACK_THEME);

  let table = $state<FitTableData | null>(null);
  let root = $state<HTMLElement | null>(null);
  let width = $state(0);
  let phoneHost = $state<string | null>(null);
  let reportedFor = '';
  const inPopout = globalThis.location?.pathname.endsWith('/popout.html') ?? false;

  const sel = $derived(link.selection);
  const widget = $derived(widgets.find((one) => one.key === sel.widget));
  const live = $derived(link.live);
  const phone = $derived(width > 0 && width <= PHONE_MAX_PX);
  const bands = $derived((widget?.hosts ?? []).filter((host) => host.supported && sel.hosts.includes(host.zone)));
  const drawn = $derived(bands.flatMap((host): { host: LabHost; dock: DrawerDock | undefined }[] => (host.zone === 'drawer' ? sel.docks.map((dock) => ({ host, dock })) : [{ host, dock: undefined }])));
  const undeclared = $derived((widget?.hosts ?? []).filter((host) => !host.supported));
  const activeHost = $derived(bands.find((host) => host.zone === phoneHost)?.zone ?? bands[0]?.zone ?? '');
  const verdict = $derived(widget ? widgetVerdict(table, widget.key) : 'none');
  const scenarioRoutes = $derived(appliedRoutes(sel.scenario));

  async function readTable(): Promise<void> {
    try {
      table = (await fitTableState()).table;
    } catch (error) {
      console.warn('[widget lab] fit table', error);
    }
  }

  onMount(() => {
    void readTable();
    return root ? watchWidth(root, (next) => (width = next)) : undefined;
  });
  onDestroy(() => link.destroy());
  $effect(() => {
    void live.matrixSeq;
    if (live.matrixSeq > 0) void readTable();
  });

  function reported(_host: string, report: FrameReport | null): void {
    const json = report?.result?.fixtureJson;
    const key = `${sel.widget}|${sel.fixture}`;
    if (!json || reportedFor === key) return;
    reportedFor = key;
    link.send({ intent: 'fixture', json });
  }

  function focus(frame: FrameRef | null): void {
    link.send({ intent: 'focus', focus: frame });
  }

  function chooseSize(host: string, size: string): void {
    link.send({ intent: 'size', host, size });
  }

  /* the real left sidebar */
  function chooseSidebar(view: SidebarView): void {
    link.send({ intent: 'sidebar', view });
  }

  function key(event: KeyboardEvent): void {
    if (event.key === 'Escape' && sel.focus) focus(null);
  }
</script>

<svelte:window onkeydown={key} />

<div class="dwl" bind:this={root} data-phone={phone ? 'yes' : 'no'}>
  {#if !inPopout}
    <div class="dwl-open-float">
      <IconButton label={t('cplug.devwidgetlab.viewer.pop_out')} variant="float" icon="external" iconSize={13} data-lab-popout
        onclick={() => openTabPopout('devwidgetlab')} />
    </div>
  {/if}
  <header class="dwl-strip">
    {#if sel.view === 'fit'}
      <span class="dwl-strip-name">{t('cplug.devwidgetlab.viewer.fit_title')}</span>
    {:else if widget}
      <span class="dwl-strip-name">{widget.title}</span><span class="dwl-hint">{widget.key}</span>
      {#if verdict !== 'none'}<span class="dwl-verdict" data-verdict={verdict}>{t(`cplug.devwidgetlab.verdict.${verdict}`)}</span>{/if}
    {/if}
    {#if !live.menuOpen}
      <div class="dwl-seg dwl-views">
        <Button size="sm" data-lab-menu onclick={() => link.send({ intent: 'open-menu' })}>{t('cplug.devwidgetlab.viewer.menu')}</Button>
      </div>
    {/if}
  </header>

  <p class="dwl-context dwl-hint">
    {t('cplug.devwidgetlab.viewer.context', { theme: sel.theme, fixture: sel.fixture })}
    / <span data-warn={sel.scenario !== null ? 'yes' : undefined}>{sel.scenario === null ? t('cplug.devwidgetlab.viewer.scenario_none') : t('cplug.devwidgetlab.viewer.scenario_routes', { count: scenarioRoutes })}</span>
  </p>

  <div class="dwl-viewer">
    {#if sel.view === 'fit'}
      <FitTable seq={live.matrixSeq} onstate={(next) => (table = next.table)}
        onpick={(key, host, size) => link.send({ intent: 'pick', widget: key, ...(host ? { host } : {}), ...(size ? { size } : {}) })} />
    {:else if sel.view === 'compare' && sel.draft}
      <DraftCompare {sel} {widgets} refreshSeq={link.draftsSeq} scale={(frame) => frameScale(phone, width, frame)} />
    {:else if widget}
      {#if phone && bands.length > 1}
        <div class="dwl-hosttabs">
          <Segmented label={t('cplug.devwidgetlab.show_in')} value={activeHost} onchange={(zone) => (phoneHost = zone)}
            options={bands.map((host) => ({ value: host.zone, label: t(`cplug.devwidgetlab.host.${host.zone}`), attrs: { 'data-host-tab': host.zone } }))} />
        </div>
      {/if}
      {#key `${widget.key}|${sel.fixture}`}
        {#each drawn as { host, dock } (`${host.zone}:${dock ?? ''}`)}
          {#if !phone || host.zone === activeHost}
            <HostBand {host} {dock} widget={widget.key} title={widget.title} icon={widget.icon} theme={sel.theme} fixture={sel.fixture} size={bandSize(host, sel)?.name ?? ''}
              scenario={sel.scenario} focus={sel.focus} {table} sidebar={sel.sidebar} onsidebar={chooseSidebar} scale={(frame) => frameScale(phone, width, frame)} onfocus={focus} onsize={chooseSize} onreport={reported} />
          {/if}
        {/each}
      {/key}
      {#each undeclared as host (host.zone)}
        <p class="dwl-note dwl-undeclared">{t('cplug.devwidgetlab.viewer.undeclared', { host: t(`cplug.devwidgetlab.host.${host.zone}`), why: t(`cplug.devwidgetlab.host.refusal.${host.refusal ?? 'none'}`, { host: t(`cplug.devwidgetlab.host.${host.zone}`) }) })}</p>
      {/each}
      <CaptureResults items={live.captures} running={live.capturing !== null} />
    {:else}
      <p class="dwl-note dwl-note--error">{t('cplug.devwidgetlab.widget.none')}</p>
    {/if}
  </div>
</div>
