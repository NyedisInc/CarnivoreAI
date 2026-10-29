<script lang="ts">
  import { t } from '../sdk';
  import type { FrameReport, LabHost, LabIcon, SidebarView } from '../sdk/widget-lab';
  import { frameVerdict, type FitTable } from './lab-model';
  import { dockBox, drawnWidth, sizesOnShow } from './dock-box';
  import type { FixtureChoice } from './frame-url';
  import { MAIN_SIZES, type DrawerDock, type FrameRef } from './lab-selection';
  import PreviewFrame from './PreviewFrame.svelte';
  import SidebarControls from './SidebarControls.svelte';

  interface Props {
    host: LabHost;
    dock?: DrawerDock;
    widget: string;
    title: string;
    icon?: LabIcon;
    theme: string;
    fixture: FixtureChoice;
    size: string;
    scenario: string | null;
    focus: FrameRef | null;
    table: FitTable | null;
    scale: (frameWidth: number) => number;
    onfocus: (frame: FrameRef | null) => void;
    onsize: (host: string, size: string) => void;
    onreport: (host: string, report: FrameReport | null) => void;
    sidebar: SidebarView;
    onsidebar: (view: SidebarView) => void;
  }

  const { host, dock = 'left', widget, title, icon, theme, fixture, size: current, scenario, focus, table, scale, onfocus, onsize, onreport, sidebar: view, onsidebar }: Props = $props();

  const isLeft = $derived(host.zone === 'drawer' && dock === 'left');
  const sizeName = $derived(current);
  const drawn = $derived(sizesOnShow(host, [sizeName], dock));
  const docked = $derived(dockBox(host.zone, dock) !== null);
  /* the real left sidebar */
  const switches = $derived(docked || isLeft ? [] : host.sizes.filter((one) => MAIN_SIZES.includes(one.name)));
  const more = $derived(docked || isLeft ? [] : host.sizes.filter((one) => !MAIN_SIZES.includes(one.name)));
  let moreOpen = $state(false);
  const lit = $derived(drawn[0]?.name ?? '');

  function choose(name: string): void {
    moreOpen = false;
    onsize(host.zone, name);
  }
  const bandDock = $derived(host.zone === 'drawer' ? dock : undefined);
  const isFocus = (name: string): boolean => focus !== null && focus.host === host.zone && focus.size === name && focus.dock === bandDock;
</script>

<section class="dwl-host" data-host={host.zone} data-dock={bandDock}>
  <header class="dwl-host-head">
    <span class="dwl-host-name">{host.zone === 'drawer' ? t(`cplug.devwidgetlab.dock.${dock}`) : t(`cplug.devwidgetlab.host.${host.zone}`)}</span>
    {#if switches.length + more.length > 1}
      <div class="dwl-band-sizes" role="group" aria-label={t('cplug.devwidgetlab.size')}>
        {#each switches as one (one.name)}
          <button type="button" class="oc-btn oc-btn--sm dwl-size-key" aria-pressed={lit === one.name} data-on={lit === one.name ? 'yes' : 'no'} data-size={one.name}
            onclick={() => choose(one.name)}>{one.name}</button>
        {/each}
        {#if more.length > 0}
          <details class="dwl-size-more" bind:open={moreOpen} data-lit={more.some((one) => one.name === lit) ? 'yes' : 'no'}>
            <summary class="oc-btn oc-btn--sm">{more.some((one) => one.name === lit) ? lit : t('cplug.devwidgetlab.sizes.more_menu')}</summary>
            <div class="dwl-size-more-list">
              {#each more as one (one.name)}
                <button type="button" class="oc-btn oc-btn--sm dwl-size-key" aria-pressed={lit === one.name} data-on={lit === one.name ? 'yes' : 'no'} data-size={one.name}
                  onclick={() => choose(one.name)}>{one.name}</button>
              {/each}
            </div>
          </details>
        {/if}
      </div>
    {/if}
    <span class="dwl-chip">{t('cplug.devwidgetlab.host.supported')}</span>
  </header>
  {#if isLeft}<SidebarControls {view} onview={onsidebar} />{/if}

  <details class="dwl-sizes">
    <summary>{t('cplug.devwidgetlab.sizes.title', { count: host.sizes.length })}</summary>
    <table class="dwl-sizes-table">
      <thead>
        <tr>
          <th>{t('cplug.devwidgetlab.sizes.name')}</th>
          <th>{t('cplug.devwidgetlab.sizes.box')}</th>
          <th>{t('cplug.devwidgetlab.sizes.window')}</th>
          <th>{t('cplug.devwidgetlab.sizes.kind')}</th>
        </tr>
      </thead>
      <tbody>
        {#each host.sizes as one (one.name)}
          <tr data-current={drawn.some((size) => size.name === one.name) ? 'yes' : 'no'}>
            <td>{one.name}</td>
            <td>{one.w} x {one.h ?? t('cplug.devwidgetlab.sizes.auto')}</td>
            <td>{one.viewport}</td>
            <td>{one.floor ? t('cplug.devwidgetlab.sizes.floor') : one.declared ? t('cplug.devwidgetlab.sizes.declared') : ''}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </details>

  <div class="dwl-previews">
    {#each drawn as size (isLeft ? 'left' : size.name)}
      {@const fit = frameVerdict(table, widget, host.zone, size.name)}
      <PreviewFrame host={host.zone} {dock} sizes={host.sizes} {size} {widget} {title} {icon} {theme} {fixture} {scenario} verdict={fit?.verdict ?? null} reasons={fit?.reasons ?? []}
        focused={isFocus(size.name)} dim={focus !== null && !isFocus(size.name)} scale={scale(drawnWidth(host.zone, dock, size))}
        view={isLeft ? view : undefined}
        onfocus={() => onfocus(isFocus(size.name) ? null : { host: host.zone, size: size.name, ...(bandDock ? { dock: bandDock } : {}) })} {onreport} />
    {/each}
  </div>
</section>
