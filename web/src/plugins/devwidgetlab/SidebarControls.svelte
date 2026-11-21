<script lang="ts">
  import { t } from '../sdk';
  import { Segmented } from '../sdk/ui';
  import { SIDEBAR_AREAS, SIDEBAR_DENSITIES, SIDEBAR_WIDTHS, type SidebarView } from '../sdk/widget-lab';

  interface Props {
    view: SidebarView;
    onview: (next: SidebarView) => void;
  }

  const { view, onview }: Props = $props();
</script>

{#snippet group(name: string, choices: readonly string[], current: string, pick: (value: string) => void)}
  <div class="dwl-band-sizes dwl-sidebar-group">
    <span class="dwl-hint">{t(`cplug.devwidgetlab.sidebar.${name}`)}</span>
    <Segmented data-group={name} label={t(`cplug.devwidgetlab.sidebar.${name}`)} value={current} onchange={pick}
      options={choices.map((choice) => ({ value: choice, label: t(`cplug.devwidgetlab.sidebar.${name}.${choice}`), attrs: { 'data-choice': choice } }))} />
  </div>
{/snippet}

<div class="dwl-sidebar-controls" data-testid="sidebar-controls">
  {@render group('width', SIDEBAR_WIDTHS, view.width, (width) => onview({ ...view, width: width as SidebarView['width'] }))}
  {@render group('fold', ['off', 'on'], view.folded ? 'on' : 'off', (fold) => onview({ ...view, folded: fold === 'on' }))}
  {@render group('area', SIDEBAR_AREAS, view.area, (area) => onview({ ...view, area: area as SidebarView['area'] }))}
  {@render group('density', SIDEBAR_DENSITIES, view.density, (density) => onview({ ...view, density: density as SidebarView['density'] }))}
</div>
