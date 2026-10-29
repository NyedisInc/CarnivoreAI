<script lang="ts">
  /* pop-out window */
  import { t } from '../sdk';
  import type { FrameReport, LabIcon, LabSize, SidebarView } from '../sdk/widget-lab';
  import type { FixtureChoice } from './frame-url';
  import { sizeLine } from './lab-model';
  import type { DrawerDock } from './lab-selection';
  import { frameBox, settledBox } from './dock-box';
  import HostChrome from './HostChrome.svelte';
  import LabFrame from './LabFrame.svelte';
  import ResizeBox from './ResizeBox.svelte';
  import { sameBox, type Box } from './resize-model';

  interface Props {
    host: string;
    dock?: DrawerDock;
    size: LabSize;
    widget: string;
    title: string;
    icon?: LabIcon;
    theme: string;
    fixture: FixtureChoice;
    page: string;
    showCurrent: boolean;
    sidebar?: SidebarView;
    scale: number;
    onreport: (host: string, size: string, side: 'current' | 'draft', report: FrameReport | null) => void;
  }

  const { host, dock = 'left', size, widget, title, icon, theme, fixture, page, showCurrent, sidebar, scale, onreport }: Props = $props();

  let custom = $state<Box | null>(null);
  let live = $state<Box | null>(null);
  let shown = $state<Box>({ w: 0, h: 0 });

  const fb = $derived(frameBox(host, dock, size, custom));
  const base = $derived({ widget, host, size: size.name, theme, fixture, scenario: false, ...fb.spec, ...(fb.sidebar && sidebar ? { view: sidebar } : {}) });
  const now = $derived(live ?? custom ?? shown);
  const resized = $derived(custom !== null || (live !== null && !sameBox(live, shown)));
  const capName = $derived(fb.docked ? t(`cplug.devwidgetlab.dock.${dock}`) : sizeLine(size));

  function changed(next: Box, final: boolean): void {
    live = final ? null : next;
    if (final) custom = settledBox(next, fb.base);
  }

  function reset(): void {
    custom = null;
    live = null;
  }
  const sides = $derived(showCurrent ? (['current', 'draft'] as const) : (['draft'] as const));
</script>

<figure class="dwl-pair" data-size={size.name} data-host={host}>
  <figcaption class="dwl-preview-cap">
    <span class="dwl-cap-text">{capName}</span>
    <span class="dwl-dims" data-resized={resized ? 'yes' : 'no'} data-testid="dims">{t('cplug.devwidgetlab.resize.readout', { w: now.w, h: now.h })}</span>
    {#if resized}<button type="button" class="oc-btn oc-btn--sm dwl-reset" onclick={reset}>{fb.docked ? t('cplug.devwidgetlab.resize.reset_dock') : t('cplug.devwidgetlab.resize.reset', { size: size.name })}</button>{/if}
  </figcaption>
  <div class="dwl-pair-sides">
    {#each sides as side (side)}
      <div class="dwl-pair-side" data-side={side}>
        <p class="dwl-side-cap" data-side={side}>{t(`cplug.devwidgetlab.compare.${side}`)}</p>
        <div class="dwl-stage">
          <div class="dwl-zoom" style:zoom={scale === 1 ? undefined : scale}>
            {#key `${page}|${widget}|${host}|${dock}|${size.name}|${theme}|${fixture}`}
              <HostChrome {host} {dock} {title} {icon}>
                <ResizeBox box={shown} {live} {scale} mode={fb.mode} onchange={changed} onreset={reset}>
                  {#key `${custom?.w ?? ''}x${custom?.h ?? ''}`}
                    <LabFrame spec={side === 'draft' ? { ...base, page } : base} size={fb.size} scenario={null} title={`${title} / ${t(`cplug.devwidgetlab.compare.${side}`)} / ${host} / ${size.name}`}
                      onreport={(report) => onreport(host, size.name, side, report)} onbox={(next) => (shown = next)} />
                  {/key}
                </ResizeBox>
              </HostChrome>
            {/key}
          </div>
        </div>
      </div>
    {/each}
  </div>
</figure>
