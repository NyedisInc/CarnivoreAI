
<script lang="ts">
  import { Button, Field, Select } from '../../../lib/base';
  import ModalShell from '../../../lib/launchpad/ModalShell.svelte';
  import ChartCanvas from './ChartCanvas.svelte';
  import AnalyticsControls from './Controls.svelte';
  import { analytics } from './state.svelte';
  import { annotations, contributions, createAnnotation, deleteAnnotation, updateAnnotation } from './api';
  import { setHidden, setPreset, setResolution, setWidgetFilter, setZoom, zoomStep } from './chart-view';
  import { formatValue, localValue } from './value-format';
  import { PRESET_MS, allowedFilters, mergeFilters } from '../../viz/plan';
  import { t } from '../../../lib/i18n/index.svelte';
  import type { Annotation, DetailsView, RangePreset, Resolution, StatsFilters } from './types';

  let { view, close }: { view: DetailsView; close: (value: null) => void } = $props();

  const PRESETS = Object.keys(PRESET_MS) as RangePreset[];
  const RESOLUTIONS: Resolution[] = ['auto', 'minute', '5minute', 'hour', 'day', 'week', 'month', 'year'];
  const DIMENSIONS = ['provider', 'host', 'project', 'model', 'agent_kind'] as const;

  let canvas = $state<ChartCanvas | null>(null);
  let notice = $state('');
  let markerLabel = $state('');
  let markerTime = $state(localValue(new Date().toISOString()));
  let markerEdit = $state<Record<string, string>>({});
  let rows = $state<{ conversation_id: string; value: number | null; samples?: number; unknown_rows?: number }[]>([]);
  let rowsUnit = $state('');
  let rowsCursor = $state<number | null>(null);
  let rowsMetric = $state('');
  let rowsFilters = $state<Record<string, string>>({});

  const config = $derived(view.config);
  const plotted = $derived(view.results.some((result) => result.series.length) && (view.units.length <= 2 || config.display.indexed === true));
  const scope = $derived({ ...mergeFilters(analytics.filters, config.filters) } as Record<string, string | undefined>);

  $effect(() => { if (!view.open) close(null); });

  function labelOf(index: number): string {
    return view.activeSeries[index]?.label || view.results[index]?.metric || '';
  }

  function fail(cause: unknown, fallback: string): void {
    notice = cause instanceof Error ? cause.message : t(fallback);
  }

  function step(scale: number, pan = 0): void {
    setZoom(view.id, zoomStep(view.range, view.baseRange, scale, pan));
  }

  async function addMarker(): Promise<void> {
    if (!markerLabel.trim()) return;
    try {
      await createAnnotation(markerLabel.trim(), new Date(markerTime).toISOString(), scope);
      markerLabel = '';
      view.setMarkers(await annotations(view.range.from, view.range.to, undefined, scope));
      notice = '';
    } catch (cause) { fail(cause, 'analytics.setting_unavailable'); }
  }

  async function saveMarker(marker: Annotation): Promise<void> {
    try {
      const saved = await updateAnnotation(marker, markerEdit[marker.id] || marker.label);
      view.setMarkers(view.markers.map((item) => item.id === marker.id ? saved : item));
      notice = '';
    } catch (cause) { fail(cause, 'analytics.setting_unavailable'); }
  }

  async function removeMarker(marker: Annotation): Promise<void> {
    try {
      await deleteAnnotation(marker);
      view.setMarkers(view.markers.filter((item) => item.id !== marker.id));
      notice = '';
    } catch (cause) { fail(cause, 'analytics.setting_unavailable'); }
  }

  async function openContributors(seriesIndex = 0, extra: Record<string, string> = {}, cursor = 0): Promise<void> {
    const series = view.activeSeries[seriesIndex];
    if (!series) return;
    const filters = allowedFilters(series.metric, mergeFilters(scope, series.filters, extra), view.quotaWindow);
    const params = new URLSearchParams({ metric: series.metric, from: view.range.from, to: view.range.to,
      timezone: analytics.timezone, resolution: config.resolution ?? 'auto', limit: '200', cursor: String(cursor) });
    for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
    try {
      const response = await contributions(params) as { items?: typeof rows; next_cursor?: number | null; unit?: string };
      rows = cursor ? [...rows, ...(response.items ?? [])] : response.items ?? [];
      rowsCursor = response.next_cursor ?? null;
      rowsUnit = response.unit ?? view.results[seriesIndex]?.unit ?? '';
      rowsMetric = series.metric;
      rowsFilters = Object.fromEntries(Object.entries(filters).filter(([, value]) => Boolean(value))) as Record<string, string>;
      notice = '';
    } catch (cause) { fail(cause, 'analytics.contributors_unavailable'); }
  }

  function csvCell(value: string | number | null | undefined): string {
    const plain = String(value ?? '');
    const safe = /^[=+@\-]/.test(plain) ? `'${plain}` : plain;
    return `"${safe.replaceAll('"', '""')}"`;
  }

  function exportCsv(): void {
    const lines = ['conversation_id,value,samples,unknown_rows', ...rows.map((row) =>
      [row.conversation_id, row.value, row.samples, row.unknown_rows].map(csvCell).join(','))];
    const url = URL.createObjectURL(new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'conversations.csv';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
</script>

<ModalShell title={view.title} overlayClass="text-prompt-modal analytics-modal" onCancel={() => close(null)}>
  {#snippet head()}
    <div class="text-prompt-modal__head analytics-modal__head" data-analytics-details={view.id}>
      <span class="text-prompt-modal__verb">&raquo; {t('analytics.details')}</span>
      <span class="analytics-modal__title">{view.title}</span>
      <span class="analytics-modal__period">{view.period}</span>
      
      <button type="button" class="modal-close" aria-label={t('analytics.close')} onclick={() => close(null)}>&times;</button>
    </div>
  {/snippet}

  {#if notice}<p class="analytics-modal__error" role="alert">{notice}</p>{/if}

  <section class="analytics-modal__region" aria-label={t('analytics.details.window')}>
    <div class="analytics-modal__fields">
      <label class="oc-select-row"><span class="oc-sub">{t('analytics.range')}</span>
        <Select size="sm" value={config.range.preset ?? ''} disabled={config.range.mode === 'pinned'} onchange={(event) => setPreset(view.id, event.currentTarget.value)}>{#snippet children()}
          <option value="">{t('analytics.range_global')}</option>{#each PRESETS as preset (preset)}<option value={preset}>{t(`analytics.preset_${preset}`)}</option>{/each}
        {/snippet}</Select></label>
      <label class="oc-select-row"><span class="oc-sub">{t('analytics.resolution')}</span>
        <Select size="sm" value={config.resolution ?? 'auto'} onchange={(event) => setResolution(view.id, event.currentTarget.value)}>{#snippet children()}
          {#each RESOLUTIONS as value (value)}<option {value}>{value}</option>{/each}
        {/snippet}</Select></label>
      {#each DIMENSIONS as dimension (dimension)}
        <label class="oc-select-row"><span class="oc-sub">{t(`analytics.${dimension}`)}</span>
          <Select size="sm" value={config.filters[dimension as keyof StatsFilters] || ''} onchange={(event) => setWidgetFilter(view.id, dimension, event.currentTarget.value)}>{#snippet children()}
            <option value="">{t('analytics.all')}</option>
            {#each analytics.dimensions[dimension] || [] as item (item.key)}{#if item.filter_value}<option value={item.filter_value}>{item.label}</option>{/if}{/each}
          {/snippet}</Select></label>
      {/each}
    </div>
    <div class="analytics-modal__actions">
      <Button size="sm" onclick={() => step(0.5)}>{t('analytics.zoom_in')}</Button>
      <Button size="sm" onclick={() => step(2)}>{t('analytics.zoom_out')}</Button>
      <Button size="sm" onclick={() => step(1, -0.25)}>{t('analytics.pan_left')}</Button>
      <Button size="sm" onclick={() => step(1, 0.25)}>{t('analytics.pan_right')}</Button>
      <Button size="sm" onclick={() => { setZoom(view.id, null); canvas?.resetZoom(); }}>{t('analytics.reset_zoom')}</Button>
    </div>
    {#if view.selectedMarker}
      <p class="analytics-modal__line">{t('analytics.comparing_marker')}: {view.selectedMarker.label}
        <Button size="sm" variant="quiet" onclick={() => view.selectMarker(null)}>{t('analytics.reset_comparison')}</Button></p>
    {/if}
  </section>

  {#if view.units.length > 2 && !config.display.indexed}<p class="analytics-modal__line" role="alert">{t('analytics.two_axes')}</p>{/if}
  {#if plotted}
    <div class="analytics-modal__plot">
      <ChartCanvas bind:this={canvas} {config} results={view.results} seriesConfigs={view.activeSeries} annotations={view.markers} thresholds={view.thresholds}
        onRangeChange={(next) => setZoom(view.id, next)} hiddenSeries={config.display.hidden_series ?? []} onHiddenChange={(hidden) => setHidden(view.id, hidden)} />
    </div>
  {/if}

  <section class="analytics-modal__region" aria-label={t('analytics.details.figures')}>
    <h3 class="oc-sub">{t('analytics.details.figures')}</h3>
    <dl class="analytics-modal__facts">
      {#each view.results as result, index (index)}
        {#if result.summary}
          <div><dt>{labelOf(index)}</dt><dd>{formatValue(typeof result.summary.value === 'number' ? result.summary.value : null, result.unit)}</dd><dd>{result.summary.samples ?? 0} {t('analytics.samples')}</dd></div>
        {/if}
        {#if result.coverage}
          <div><dt>{t('analytics.coverage')}</dt><dd>{result.coverage.observed_minutes ?? 0}/{result.coverage.range_minutes ?? 0} {t('analytics.observed_minutes')}</dd>
            {#if result.coverage.partial || result.coverage.unknown_value_rows}<dd>{#if result.coverage.partial}{t('analytics.partial')}{/if}{#if result.coverage.unknown_value_rows} {result.coverage.unknown_value_rows} {t('analytics.unknown_rows')}{/if}</dd>{/if}</div>
        {/if}
      {/each}
    </dl>
    {#if view.results.some((result) => result.price_basis)}<p class="analytics-modal__line">{t('analytics.cost_estimate')}</p>{/if}

    {#each view.results as result, index (index)}
      {#if result.ranking?.length}
        {@const groupBy = view.activeSeries[index]?.group_by}
        <table class="analytics-modal__table"><caption>{labelOf(index)} · {t('analytics.ranking')}</caption>
          <thead><tr><th scope="col">{t('analytics.name')}</th><th scope="col">{t('analytics.value')}</th><th scope="col">{t('analytics.samples')}</th></tr></thead>
          <tbody>{#each result.ranking as rank (rank.key)}<tr>
            <th scope="row">{#if rank.filter_value && groupBy && result.metric !== 'quota_utilization'}<Button size="sm" variant="quiet" onclick={() => openContributors(index, { [groupBy]: rank.filter_value! })}>{rank.label}</Button>{:else}{rank.label}{/if}</th>
            <td>{formatValue(rank.value, result.unit)}</td><td>{rank.samples ?? ''}</td></tr>{/each}</tbody>
        </table>
      {/if}
      {#if result.comparison}
        <table class="analytics-modal__table"><caption>{t('analytics.before_after')} · {labelOf(index)}</caption>
          <thead><tr><th scope="col">{t('analytics.period')}</th><th scope="col">{t('analytics.value')}</th><th scope="col">{t('analytics.samples')}</th></tr></thead>
          <tbody>
            <tr><th scope="row">{t('analytics.before')}</th><td>{formatValue(result.comparison.summary?.value ?? null, result.unit)}</td><td>{result.comparison.summary?.samples ?? 0}</td></tr>
            <tr><th scope="row">{t('analytics.after')}</th><td>{formatValue(typeof result.summary?.value === 'number' ? result.summary.value : null, result.unit)}</td><td>{result.summary?.samples ?? 0}</td></tr>
          </tbody>
        </table>
        <p class="analytics-modal__line">{t('analytics.comparison_caution')}</p>
      {/if}
      {#if result.series.length}
        <details class="analytics-modal__more"><summary>{labelOf(index)} · {t('analytics.data_table')}</summary>
          <table class="analytics-modal__table analytics-modal__table--points"><thead><tr><th scope="col">{t('analytics.time')}</th><th scope="col">{t('analytics.name')}</th><th scope="col">{t('analytics.value')}</th><th scope="col">{t('analytics.samples')}</th></tr></thead><tbody>
            {#each result.series as series (series.key)}{#each series.points as point (point.time)}<tr><th scope="row">{new Date(point.time).toLocaleString()}</th><td>{series.label}</td><td>{formatValue(point.value, result.unit)}</td><td>{point.samples ?? ''}</td></tr>{/each}{/each}
          </tbody></table>
        </details>
      {/if}
    {/each}
  </section>

  <section class="analytics-modal__region" aria-label={t('analytics.details.events')}>
    <details class="analytics-modal__more"><summary>{t('analytics.details.events')} · {view.markers.length}</summary>
      {#if view.markers.length}
        <ol class="analytics-modal__events">
          {#each view.markers as marker (marker.id)}
            <li>
              <time>{new Date(marker.occurred_at * 1000).toLocaleString()}</time>
              {#if marker.kind === 'manual'}
                <Field aria-label={t('analytics.annotation_label')} value={markerEdit[marker.id] ?? marker.label} oninput={(event) => { markerEdit[marker.id] = event.currentTarget.value; }} />
                <span class="analytics-modal__row-actions">
                  <Button size="sm" onclick={() => saveMarker(marker)}>{t('analytics.save')}</Button>
                  <Button size="sm" variant="quiet" onclick={() => removeMarker(marker)}>{t('analytics.remove')}</Button>
                </span>
              {:else}
                <span class="analytics-modal__event-label">{marker.label}{#if marker.basis}{` · ${marker.basis}`}{/if}</span>
                <span class="analytics-modal__row-actions"><Button size="sm" aria-pressed={view.selectedMarker?.id === marker.id} onclick={() => view.selectMarker(marker)}>{t('analytics.compare')}</Button></span>
              {/if}
            </li>
          {/each}
        </ol>
      {/if}
      <div class="analytics-modal__form">
        <label class="oc-select-row"><span class="oc-sub">{t('analytics.compare_hours')}</span>
          <Select size="sm" value={String(view.comparisonHours)} onchange={(event) => view.setComparisonHours(Number(event.currentTarget.value))}>{#snippet children()}<option value={1}>1</option><option value={24}>24</option><option value={168}>168</option>{/snippet}</Select></label>
        <label class="oc-select-row analytics-modal__grow"><span class="oc-sub">{t('analytics.annotation_label')}</span><Field maxlength={240} bind:value={markerLabel}  /></label>
        <label class="oc-select-row"><span class="oc-sub">{t('analytics.time')}</span><Field type="datetime-local" bind:value={markerTime}  /></label>
        <Button disabled={!markerLabel.trim()} onclick={addMarker}>{t('analytics.add_annotation')}</Button>
      </div>
    </details>
  </section>

  {#if view.activeSeries[0]?.metric !== 'quota_utilization'}
    <section class="analytics-modal__region" aria-label={t('analytics.contributing_conversations')}>
      <div class="analytics-modal__actions">
        <Button size="sm" onclick={() => openContributors(0)}>{t('analytics.details.show_conversations')}</Button>
        {#if rows.length}<Button size="sm" onclick={exportCsv}>{t('analytics.export_csv')}</Button>{/if}
      </div>
      {#if rows.length}
        <table class="analytics-modal__table analytics-modal__table--ids"><caption>{t('analytics.contributing_conversations')}</caption>
          <thead><tr><th scope="col">{t('analytics.conversation')}</th><th scope="col">{t('analytics.value')}</th><th scope="col">{t('analytics.samples')}</th></tr></thead>
          <tbody>{#each rows as row (row.conversation_id)}<tr><th scope="row">{row.conversation_id}</th><td>{formatValue(row.value, rowsUnit)}</td><td>{row.samples ?? ''}</td></tr>{/each}</tbody>
        </table>
        {#if rowsCursor !== null}<Button size="sm" onclick={() => openContributors(view.activeSeries.findIndex((series) => series.metric === rowsMetric), rowsFilters, rowsCursor ?? 0)}>{t('analytics.more')}</Button>{/if}
      {/if}
    </section>
  {/if}

  <section class="analytics-modal__region" aria-label={t('analytics.filters')}>
    <AnalyticsControls />
  </section>

  {#snippet footer()}
    <button type="button" class="modal-btn modal-btn-secondary" onclick={() => close(null)}>{t('modal.close')}</button>
  {/snippet}
</ModalShell>

<style>
  :global(.text-prompt-modal.analytics-modal .modal-content) {
    display: flex;
    flex-direction: column;
    box-sizing: border-box;
    width: min(960px, calc(100vw - 32px));
    max-width: none;
    max-height: calc(100dvh - 32px);
  }

  :global(.text-prompt-modal.analytics-modal .modal-body) {
    flex: 1 1 auto;
    min-height: 0;
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 0;
  }

  :global(.text-prompt-modal.analytics-modal .modal-footer) {
    flex: none;
    box-shadow: inset 0 1px 0 0 var(--oc-line-rule);
    padding: var(--oc-space-3) 14px;
  }

  @media (max-width: 600px) {
    :global(.text-prompt-modal.analytics-modal .modal-content) {
      width: 100vw;
      height: 100dvh;
      max-height: 100dvh;
      border: 0;
      border-radius: 0;
    }
  }

  @layer components {
    .analytics-modal__title { flex: 1 1 auto; min-width: 0; overflow: hidden; color: var(--oc-text-primary); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }

    .analytics-modal__period { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; }

    .analytics-modal__region { display: flex; flex-direction: column; gap: var(--oc-space-3); padding: var(--oc-space-4) 14px; box-shadow: inset 0 1px 0 0 var(--oc-line-faint); font-family: var(--font-mono); font-size: var(--oc-fs-label); color: var(--oc-text-secondary); }

    .analytics-modal__region:first-of-type { box-shadow: none; }

    .analytics-modal__region h3 { margin: 0; font-weight: 400; }

    .analytics-modal__fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--oc-space-3); }

    .analytics-modal__fields :global([data-field]) { width: 100%; min-width: 0; }

    .analytics-modal__actions, .analytics-modal__form { display: flex; flex-wrap: wrap; align-items: flex-end; gap: var(--oc-space-2); }

    .analytics-modal__grow { flex: 1 1 200px; }

    .analytics-modal__grow :global([data-field]) { width: 100%; }

    .analytics-modal__line { margin: 0; color: var(--oc-text-secondary); line-height: 1.5; }

    .analytics-modal__error { margin: var(--oc-space-3) 14px 0; padding: 6px var(--oc-space-2); border-left: 2px solid var(--oc-coral); background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-raised)); color: var(--oc-text-primary); line-height: 1.45; }

    .analytics-modal__plot { height: 300px; margin: 0 var(--oc-space-2) var(--oc-space-3); }

    .analytics-modal__facts { display: grid; gap: 0; margin: 0; }

    .analytics-modal__facts div { display: flex; align-items: baseline; gap: var(--oc-space-4); padding: 5px 0; box-shadow: inset 0 -1px 0 0 var(--oc-line-faint); }

    .analytics-modal__facts dt { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; color: var(--oc-text-muted); }

    .analytics-modal__facts dd { flex: none; margin: 0; color: var(--oc-text-primary); text-align: right; font-variant-numeric: tabular-nums; }

    .analytics-modal__table { width: 100%; table-layout: fixed; border-collapse: collapse; text-align: left; font-variant-numeric: tabular-nums; }

    .analytics-modal__table caption { padding: 0 0 var(--oc-space-2); color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: 0.8px; text-align: left; text-transform: uppercase; }

    .analytics-modal__table th, .analytics-modal__table td { padding: 5px var(--oc-space-2) 5px 0; overflow-wrap: anywhere; box-shadow: inset 0 -1px 0 0 var(--oc-line-faint); font-weight: 400; vertical-align: baseline; }

    .analytics-modal__table thead th { color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: 0.8px; text-transform: uppercase; }

    .analytics-modal__table tbody th { color: var(--oc-text-primary); }

    .analytics-modal__table td { color: var(--oc-text-secondary); }

    .analytics-modal__table td:last-child, .analytics-modal__table th:last-child { width: 80px; text-align: right; padding-right: 0; }

    .analytics-modal__table--points th:first-child { width: 34%; }

    .analytics-modal__table--ids tbody th { font-size: var(--oc-fs-micro); }

    .analytics-modal__table :global([data-btn]) { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }

    .analytics-modal__more summary { cursor: pointer; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); letter-spacing: 0.8px; text-transform: uppercase; }

    .analytics-modal__more[open] summary { margin-bottom: var(--oc-space-3); }

    .analytics-modal__events { display: grid; margin: 0 0 var(--oc-space-3); padding: 0; list-style: none; }

    .analytics-modal__events li { display: grid; grid-template-columns: 190px minmax(0, 1fr) auto; align-items: center; gap: var(--oc-space-3); min-height: 30px; padding: 3px 0; box-shadow: inset 0 -1px 0 0 var(--oc-line-faint); }

    .analytics-modal__events time { color: var(--oc-text-muted); font-variant-numeric: tabular-nums; }

    .analytics-modal__event-label { min-width: 0; overflow-wrap: anywhere; color: var(--oc-text-primary); }

    .analytics-modal__row-actions { display: flex; gap: var(--oc-space-1); justify-content: flex-end; }

    @media (max-width: 600px) {
      .analytics-modal__plot { height: 220px; margin: 0 0 var(--oc-space-2); }

      .analytics-modal__fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }

      .analytics-modal__actions > :global([data-btn]) { flex: 1 1 auto; }

      .analytics-modal__events li { grid-template-columns: minmax(0, 1fr) auto; }

      .analytics-modal__events time { grid-column: 1 / -1; }
    }
  }
</style>
