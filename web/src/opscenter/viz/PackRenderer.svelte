<script lang="ts">
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { emptyLine } from './empty';
  import type { RendererProps } from './registry';
  import VizSettings from './VizSettings.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { packMachines } from '../../lib/pack-machines/pack-machines-store.svelte';
  import { packModel, type PackBox } from './pack';

  let { config, tier }: RendererProps = $props();
  const framing = framedTitle();
  const model = $derived(packModel(packMachines.data));
  const PANEL_AGENTS = 3;

  function fig(value: number | null, unit = ''): string {
    return value === null ? '-' : `${Math.round(value)}${unit}`;
  }
  function silence(box: PackBox): string {
    return t(`pack.machines.state.${box.state}`);
  }
</script>

<section class="viz-pack viz-pack--{tier}" aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-pack__note">{t('analytics.chart_disabled')}</p>
  {:else}
    <header class="viz-pack__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if model.totals.machines > 0}<span>{t('pack.analytics.reporting', { reporting: model.totals.reporting, machines: model.totals.machines })}</span>{/if}</header>
    {#if model.totals.machines === 0}
      <EmptyState line={emptyLine('live')} />
    {:else}
      {#if tier !== 'tile'}
        <ol class="viz-pack__boxes" data-pack="boxes">
          {#each model.boxes as box (box.installId)}
            <li class="viz-pack__box" class:viz-pack__box--over={box.overLine} data-pack-box={box.installId}>
              <div class="viz-pack__boxhead">
                <strong class="viz-pack__name" title={box.label}>{box.label}</strong>
                {#if box.isMaster}<span class="viz-pack__master" data-pack-master>{t('pack.machines.master')}</span>{/if}
                {#if box.level}<span class="viz-pack__level" data-pack-level={box.level}>{t(`pack.machines.level.${box.level}`)}</span>{#if box.reserveCpuPct !== null && box.reserveMemPct !== null}<span class="viz-pack__state" data-pack-reserve>{t('pack.analytics.reserve_figs', { cpu: box.reserveCpuPct, mem: box.reserveMemPct })}</span>{/if}{/if}
                {#if !box.live}<span class="viz-pack__state">{silence(box)}</span>{/if}
              </div>
              {#if box.live}
                <div class="viz-pack__bar" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow={box.barPct ?? undefined}
                  aria-label={t('pack.analytics.load')} data-pack-bar>
                  {#if box.barPct !== null}<span class="viz-pack__fill" style:width="{box.barPct}%"></span>{/if}
                  {#if box.linePct !== null && box.level}
                    <span class="viz-pack__line" style:left="{box.linePct}%" data-pack-line={box.linePct}
                      title={t('pack.analytics.line', { level: t(`pack.machines.level.${box.level}`), percent: box.reserveCpuPct ?? 0 })}></span>
                  {/if}
                </div>
                <dl class="viz-pack__stats">
                  <div><dt>{t('pack.analytics.load')}</dt><dd>{fig(box.loadPct, '%')}{#if box.cores !== null}<small> / {box.cores} {t('pack.machines.cores')}</small>{/if}</dd></div>
                  <div><dt>{t('pack.machines.cpu')}</dt><dd>{fig(box.cpuPct, '%')}</dd></div>
                  <div><dt>{t('pack.machines.mem')}</dt><dd>{fig(box.memPct, '%')}</dd></div>
                  <div><dt>{t('pack.machines.disk')}</dt><dd>{fig(box.diskPct, '%')}</dd></div>
                  {#if box.battery}<div><dt>{t('pack.analytics.battery')}</dt><dd>{fig(box.battery.percent, '%')}{#if box.battery.onBattery}<small> {t('pack.analytics.on_battery')}</small>{/if}</dd></div>{/if}
                  <div class="viz-pack__sum" data-pack-sum><dt>{t('pack.analytics.agents')}</dt><dd>{box.agentCount === null ? '-' : box.agentCount}{#if box.agentCores !== null}<small>{t('pack.analytics.agent_figs', { cores: box.agentCores, mb: fig(box.agentRssMb, ' mb') })}</small>{/if}</dd></div>
                </dl>
                {#if box.overLine}<p class="viz-pack__flag">{t('pack.analytics.over_line')}{#if box.throttled > 0} - {t('pack.analytics.throttled', { count: box.throttled })}{/if}</p>{/if}
                {#if tier === 'panel' && box.agents.length > 0}
                  <ul class="viz-pack__agents">
                    {#each box.agents.slice(0, PANEL_AGENTS) as agent (agent.session_uuid)}
                      <li><span class="viz-pack__agent" title={agent.name}>{agent.name}</span><span>{fig(agent.cpu_pct, '%')}</span><span>{fig(agent.rss_mb, ' mb')}</span></li>
                    {/each}
                    {#if box.agents.length > PANEL_AGENTS || box.more > 0}<li class="viz-pack__more">{t('pack.analytics.more', { count: box.agents.length - PANEL_AGENTS + box.more })}</li>{/if}
                  </ul>
                {/if}
              {/if}
            </li>
          {/each}
        </ol>
      {/if}
      <footer class="viz-pack__total" data-pack="total">
        <strong>{t('pack.analytics.total')}</strong>
        <span data-pack-total="agents">{model.totals.agents === null ? '-' : model.totals.agents} {t('pack.analytics.agents')}</span>
        <span data-pack-total="cores">{model.totals.agentCores === null ? '-' : model.totals.agentCores} / {model.totals.cores === null ? '-' : model.totals.cores} {t('pack.machines.cores')}</span>
        <span data-pack-total="mem">{fig(model.totals.agentRssMb, ' mb')}</span>
        {#if model.totals.silent > 0}<span class="viz-pack__state">{t('pack.analytics.silent', { count: model.totals.silent })}</span>{/if}
      </footer>
      {#if tier === 'full' && model.agents.length > 0}
        <table class="viz-pack__table" data-pack="agents">
          <thead><tr><th>{t('pack.analytics.col_agent')}</th><th>{t('pack.analytics.col_machine')}</th><th>{t('pack.machines.cpu')}</th><th>{t('pack.machines.mem')}</th></tr></thead>
          <tbody>
            {#each model.agents as agent (agent.machineId + agent.session_uuid)}
              <tr data-pack-agent={agent.session_id}><td class="viz-pack__agent" title={agent.name}>{agent.name}</td><td>{agent.machine}</td><td>{fig(agent.cpu_pct, '%')}</td><td>{fig(agent.rss_mb, ' mb')}</td></tr>
            {/each}
          </tbody>
        </table>
      {/if}
    {/if}
  {/if}
  <VizSettings {config} metric={false} range={false} />
</section>

<style>
  @layer components {
    .viz-pack { display: flex; flex-direction: column; gap: var(--oc-space-2); min-width: 0; height: 100%; overflow: auto; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-pack__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-pack__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-pack__head span, .viz-pack__state { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-pack__boxes { display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: var(--oc-space-3); margin: 0; padding: 0; list-style: none; }

    .viz-pack__box { display: flex; flex-direction: column; gap: var(--oc-space-1); min-width: 0; padding-bottom: var(--oc-space-2); box-shadow: 0 1px 0 var(--oc-line-faint); }

    .viz-pack__boxhead { display: flex; align-items: baseline; gap: var(--oc-space-2); min-width: 0; }

    .viz-pack__name { min-width: 0; overflow: hidden; color: var(--oc-text-primary); text-overflow: ellipsis; white-space: nowrap; }

    .viz-pack__master { flex: none; color: var(--oc-orange); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-pack__level { flex: none; color: var(--oc-cyan); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-pack__bar { position: relative; height: .5rem; background: var(--oc-ground-field); box-shadow: inset 0 0 0 1px var(--oc-line-panel); }

    .viz-pack__fill { position: absolute; inset: 0 auto 0 0; background: var(--oc-green); }

    .viz-pack__box--over .viz-pack__fill { background: var(--oc-coral); }

    .viz-pack__line { position: absolute; top: -2px; bottom: -2px; width: 2px; margin-left: -1px; background: var(--oc-yellow-bright); }

    .viz-pack__stats { display: flex; flex-wrap: wrap; gap: var(--oc-space-1) var(--oc-space-4); margin: 0; }

    .viz-pack__stats div { display: flex; flex-direction: column; min-width: 0; }

    .viz-pack__stats dt, .viz-pack__table th { color: var(--oc-text-muted); font-size: var(--oc-fs-micro); font-weight: 400; letter-spacing: .08em; text-align: left; text-transform: uppercase; }

    .viz-pack__stats dd { margin: 0; color: var(--oc-text-primary); font-variant-numeric: tabular-nums; }

    .viz-pack__stats small { color: var(--oc-text-muted); font-size: var(--oc-fs-micro); }

    .viz-pack__flag { margin: 0; color: var(--oc-coral); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-pack__agents { margin: 0; padding: 0; list-style: none; }

    .viz-pack__agents li { display: flex; gap: var(--oc-space-2); min-width: 0; color: var(--oc-text-secondary); font-variant-numeric: tabular-nums; }

    .viz-pack__agents li > span:not(.viz-pack__agent) { flex: none; min-width: 5ch; text-align: right; }

    .viz-pack__agent { flex: 1 1 auto; min-width: 0; overflow: hidden; color: var(--oc-cyan); text-overflow: ellipsis; white-space: nowrap; }

    .viz-pack__more { color: var(--oc-text-muted); font-size: var(--oc-fs-micro); }

    .viz-pack__total { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--oc-space-1) var(--oc-space-4); font-variant-numeric: tabular-nums; }

    .viz-pack__total strong { color: var(--oc-orange); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }

    .viz-pack--tile .viz-pack__total { flex: 1; align-content: center; font-size: var(--oc-fs-figure); }

    .viz-pack__table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }

    .viz-pack__table td { max-width: 18ch; padding: var(--oc-space-1) var(--oc-space-2) var(--oc-space-1) 0; overflow: hidden; color: var(--oc-text-secondary); text-overflow: ellipsis; white-space: nowrap; box-shadow: 0 1px 0 var(--oc-line-faint); }

    .viz-pack__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
