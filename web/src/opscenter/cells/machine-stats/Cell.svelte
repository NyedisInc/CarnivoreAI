<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const MACHINE_STATS_WIDGET = defineWidget({ id: 'core.machine-stats', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  /* could not measure */
  import type { CellProps } from '../../lib/cell';
  import { acquireMachineStats, machineStats } from './store.svelte';
  import { readings, toneOf } from './meta';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { stateKindOf } from '../../../lib/base/state-kind';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let props: CellProps = $props();
  const widget = useWidget(MACHINE_STATS_WIDGET, () => props);

  $effect(() => acquireMachineStats());

  const wide = $derived(widget.widthState === 'wide');
  const tall = $derived(widget.heightState === 'all');

  const resourceNow = $derived(machineStats.current);
  const rawData = $derived(resourceNow?.status === 'ok' && resourceNow.data ? resourceNow.data : null);
  const packMachines = $derived(rawData && Array.isArray(rawData.machines) && rawData.machines.length > 1 ? rawData.machines : []);
  const packMode = $derived(packMachines.length > 1);
  const primaryStats = $derived(rawData ? (packMode && rawData.pack_aggregate ? rawData.pack_aggregate : rawData) : null);
  const list = $derived(primaryStats ? readings(primaryStats) : null);
  const shown = $derived(list ? (wide || tall ? list : list.slice(0, 3)) : []);

  function pctLabel(value: number | null): string {
    return value === null ? '—' : `${Math.round(value)}%`;
  }

  const notice = $derived.by((): string => {
    if (list) return '';
    if (!resourceNow || resourceNow.status === 'loading') return t('opscenter.machine_stats.loading');
    if (resourceNow.status === 'signed-out') return t('opscenter.machine_stats.signed_out');
    return resourceNow.error ?? t('opscenter.machine_stats.error');
  });
</script>

<WidgetShell {widget}>
{#if notice}
  <State inline kind={stateKindOf(resourceNow?.status)} title={notice} />
{:else}
  <div class="oc-ms-wrap" class:oc-ms-wrap--pack={packMode} data-pack-mode={packMode ? 'true' : undefined}>
    <div class="oc-ms" class:oc-ms--wide={wide} class:oc-ms--tall={tall && !wide} data-machine-stats>
      {#each shown as r (r.key)}
        <div class="oc-ms-meter" data-meter={r.key}>
          <span class="oc-ms-label">{r.label}</span>
          <span class="oc-ms-figure" class:oc-ms-figure--none={!r.measured}>{r.figure}</span>
          {#if r.percent !== null}
            <span class="oc-ms-bar" role="presentation"><span class="oc-ms-fill oc-ms-fill--{toneOf(r.percent)}" style={`width: ${Math.min(100, Math.max(0, r.percent))}%`}></span></span>
          {/if}
          {#if r.sub && (wide || tall || r.percent === null)}
            <span class="oc-ms-sub" class:oc-ms-sub--below={tall && !wide && r.percent !== null}>{r.sub}</span>
          {/if}
        </div>
      {/each}
    </div>
    {#if packMode}
      <div class="oc-ms-pack" data-pack-machines>
        {#each packMachines as m (m.install_id)}
          <div class="oc-ms-pack-row" data-pack-machine={m.install_id}>
            <span class="oc-ms-pack-label">{m.label}</span>
            <span class="oc-ms-pack-stat" data-pack-cpu>{t('opscenter.machine_stats.cpu')} {pctLabel(m.cpu_percent)}</span>
            <span class="oc-ms-pack-stat" data-pack-mem>{t('opscenter.machine_stats.memory')} {pctLabel(m.memory_percent)}</span>
            <span class="oc-ms-pack-stat" data-pack-disk>{t('opscenter.machine_stats.disk')} {pctLabel(m.disk_percent)}</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>
{/if}
</WidgetShell>

<style>
  @layer components {

    .oc-ms-wrap {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-width: 0;
    }

    .oc-ms-wrap--pack .oc-ms {
      flex: 1 1 auto;
      height: auto;
    }

    .oc-ms-pack {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-0-5);
      padding: var(--oc-space-1) calc(var(--oc-space-2) + var(--oc-space-0-5));
      border-top: var(--oc-border) solid var(--oc-line-frame);
      font-family: var(--font-mono);
      overflow-y: auto;
    }

    .oc-ms-pack-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto auto;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
    }

    .oc-ms-pack-label {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label);
      color: var(--oc-text-bright);
    }

    .oc-ms-pack-stat {
      white-space: nowrap;
      font-size: var(--oc-fs-micro);
      color: var(--oc-text-secondary);
    }

    .oc-ms {
      display: flex;
      flex-direction: column;
      justify-content: space-around;
      height: 100%;
      min-width: 0;
      padding: var(--oc-space-1) calc(var(--oc-space-2) + var(--oc-space-0-5));
      font-family: var(--font-mono);
    }

    .oc-ms-meter {
      display: grid;
      grid-template-columns: 44px minmax(0, 1fr) 40px;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
    }

    .oc-ms-label {
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label);
      text-transform: uppercase;
      color: var(--oc-text-secondary);
    }

    .oc-ms-figure {
      grid-column: 3;
      grid-row: 1;
      text-align: right;
      font-size: var(--oc-fs-body);
      font-weight: 700;
      color: var(--oc-text-bright);
      white-space: nowrap;
    }

    .oc-ms-bar {
      grid-column: 2;
      grid-row: 1;
      display: block;
      height: 6px;
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 0 0 var(--oc-border) var(--oc-line-frame);
      border-radius: var(--oc-radius-sm);
      overflow: hidden;
    }

    .oc-ms-fill {
      display: block;
      height: 100%;
      background: var(--oc-cyan);
    }

    .oc-ms-fill--warn {
      background: var(--oc-yellow);
    }

    .oc-ms-fill--hot {
      background: var(--oc-coral);
    }

    .oc-ms--wide {
      flex-direction: row;
      justify-content: stretch;
      gap: 0;
      padding: 0;
    }

    .oc-ms--wide .oc-ms-meter {
      display: flex;
      flex: 1 1 0;
      flex-direction: column;
      justify-content: center;
      align-items: stretch;
      gap: calc(var(--oc-space-1) - var(--oc-border));
      padding: 0 var(--oc-space-3);
      box-shadow: inset var(--oc-border) 0 0 var(--oc-line-frame);
    }

    .oc-ms--wide .oc-ms-meter:first-child {
      box-shadow: none;
    }

    .oc-ms-figure--none {
      grid-column: 2 / 4;
      overflow: hidden;
      font-size: var(--oc-fs-micro);
      font-weight: 400;
      text-overflow: ellipsis;
      color: var(--oc-text-secondary);
    }

    .oc-ms-figure--none ~ .oc-ms-sub {
      grid-row: 2;
    }

    .oc-ms--wide .oc-ms-figure {
      text-align: left;
      font-size: var(--oc-fs-figure);
      line-height: 22px;
    }

    .oc-ms--tall {
      justify-content: space-evenly;
      gap: var(--oc-space-1);
    }

    .oc-ms-meter > .oc-ms-sub {
      grid-column: 2;
      grid-row: 1;
    }

    .oc-ms--wide .oc-ms-meter > .oc-ms-sub {
      grid-column: auto;
      grid-row: auto;
    }

    .oc-ms--tall .oc-ms-sub--below {
      grid-column: 2;
      grid-row: 2;
    }

    .oc-ms-sub {
      min-width: 0;
      overflow: hidden;
      font-size: var(--oc-fs-micro);
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--oc-text-dim);
    }
  }
</style>
