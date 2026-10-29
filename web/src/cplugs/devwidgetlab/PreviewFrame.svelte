<script lang="ts">
  import { t } from '../sdk';
  import type { FrameReport, LabIcon, LabSize, SidebarView } from '../sdk/widget-lab';
  import type { FixtureChoice } from './frame-url';
  import type { FrameVerdict } from './lab-model';
  import { sizeLine } from './lab-model';
  import type { DrawerDock } from './lab-selection';
  import HostChrome from './HostChrome.svelte';
  import IdleReadout from './IdleReadout.svelte';
  import LabFrame from './LabFrame.svelte';
  import ResizeBox from './ResizeBox.svelte';
  import { frameBox, settledBox } from './dock-box';
  import { nearestSize, sameBox, type Box } from './resize-model';

  interface Props {
    host: string;
    dock?: DrawerDock;
    sizes: readonly LabSize[];
    size: LabSize;
    widget: string;
    title: string;
    icon?: LabIcon;
    theme: string;
    fixture: FixtureChoice;
    scenario: string | null;
    verdict: FrameVerdict | null;
    reasons: readonly string[];
    focused: boolean;
    dim: boolean;
    scale: number;
    view?: SidebarView;
    onfocus: () => void;
    onreport: (host: string, report: FrameReport | null) => void;
  }

  const { host, dock = 'left', sizes, size, widget, title, icon, theme, fixture, scenario, verdict, reasons, focused, dim, scale, view, onfocus, onreport }: Props = $props();

  let report = $state<FrameReport | null>(null);
  let shownBox = $state<Box>({ w: 0, h: 0 });
  let custom = $state<Box | null>(null);
  let live = $state<Box | null>(null);

  const fb = $derived(frameBox(host, dock, size, custom));
  const docked = $derived(fb.docked);
  const spec = $derived({ widget, host, size: size.name, theme, fixture, scenario: scenario !== null, ...fb.spec, ...(fb.sidebar && view ? { view } : {}) });
  const frameSize = $derived<LabSize>(fb.size);
  const inPlace = $derived(fb.sidebar);
  const now = $derived(live ?? custom ?? shownBox);
  const nearest = $derived(nearestSize(sizes, now)?.name ?? size.name);
  const resized = $derived(custom !== null || (live !== null && !sameBox(live, shownBox)));
  const capName = $derived(docked || fb.sidebar ? t(`cplug.devwidgetlab.dock.${dock}`) : sizeLine(size));
  const findings = $derived(report?.result?.findings ?? []);

  function changed(next: Box, final: boolean): void {
    live = final ? null : next;
    if (!final) return;
    custom = settledBox(next, fb.base);
    report = null;
  }

  function reset(): void {
    custom = null;
    live = null;
    report = null;
  }

  function reported(next: FrameReport | null): void {
    report = next;
    onreport(host, next);
  }
</script>

<figure class="dwl-preview" data-size={size.name} data-focused={focused ? 'yes' : 'no'} data-dim={dim ? 'yes' : 'no'}>
  <figcaption class="dwl-preview-cap">
    <button type="button" class="dwl-cap-key" aria-pressed={focused} title={t('cplug.devwidgetlab.frame.focus')} onclick={onfocus}>{capName}</button>
    {#if verdict && !docked && !fb.sidebar}
      {@const word = t(`cplug.devwidgetlab.fit.cell.${verdict === 'clip' ? 'red' : verdict}`)}
      <span class="dwl-verdict" data-verdict={verdict === 'pass' ? 'pass' : 'fail'} data-for={resized ? 'size' : undefined}>{resized ? t('cplug.devwidgetlab.resize.verdict_for', { verdict: word, size: size.name }) : word}</span>
    {/if}
    <span class="dwl-dims" data-resized={resized ? 'yes' : 'no'} data-testid="dims">{t('cplug.devwidgetlab.resize.readout', { w: now.w, h: now.h })}
      {#if !docked && !fb.sidebar}<span class="dwl-hint">{t('cplug.devwidgetlab.resize.nearest', { size: nearest })}</span>{/if}</span>
    <IdleReadout {spec} size={frameSize} />
    {#if resized}<button type="button" class="oc-btn oc-btn--sm dwl-reset" onclick={reset}>{docked ? t('cplug.devwidgetlab.resize.reset_dock') : t('cplug.devwidgetlab.resize.reset', { size: size.name })}</button>{/if}
  </figcaption>
  <div class="dwl-stage">
    <div class="dwl-zoom" data-scale={scale.toFixed(2)} style:zoom={scale === 1 ? undefined : scale}>
      {#key `${widget}|${host}|${dock}|${inPlace ? '' : size.name}|${theme}|${fixture}|${scenario ?? ''}`}
        <HostChrome {host} {dock} {title} {icon}>
          <ResizeBox box={shownBox} {live} {scale} mode={fb.mode} onchange={changed} onreset={reset}>
            {#key `${custom?.w ?? ''}x${custom?.h ?? ''}`}
              <LabFrame {spec} size={frameSize} redraw={inPlace} {scenario} title={`${title} / ${host} / ${size.name}`} onreport={reported} onbox={(next) => (shownBox = next)} />
            {/key}
          </ResizeBox>
        </HostChrome>
      {/key}
    </div>
  </div>

  {#each reasons as reason}<p class="dwl-note dwl-note--error">{reason}</p>{/each}
  {#if report}
    {#if report.error}<p class="dwl-note dwl-note--error">{report.error}</p>{/if}
    {#if !report.result?.hasFixture}<p class="dwl-note dwl-note--error">{t('cplug.devwidgetlab.frame.no_fixture')}</p>{/if}
    {#if custom}<p class="dwl-note">{t('cplug.devwidgetlab.resize.checked', { w: custom.w, h: custom.h })}</p>{/if}
    {#if report.result?.plate}<p class="dwl-note">{t('cplug.devwidgetlab.frame.plate')}</p>{/if}
    {#if findings.length}
      <ul class="dwl-findings">
        {#each findings as finding}<li>{finding.rule}: {finding.detail}</li>{/each}
      </ul>
    {/if}
    {#if report.result?.unusedScenarioRoutes?.length}
      <p class="dwl-note dwl-note--error">{t('cplug.devwidgetlab.scenario.unused', { routes: report.result.unusedScenarioRoutes.join(', ') })}</p>
    {/if}
  {:else}
    <p class="dwl-note">{t('cplug.devwidgetlab.frame.waiting')}</p>
  {/if}
</figure>
