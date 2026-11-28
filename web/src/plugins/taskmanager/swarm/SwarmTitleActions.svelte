<script lang="ts">
  import { openCplugPage, t } from '../../sdk';
  import { IconButton, Segmented, type SegmentedOption } from '../../sdk/ui';
  import { DENSITIES } from '../huddle-density';
  import { swarmView, setSwarmView, type SwarmView } from '../huddle-swarm-view.svelte';
  import { effectiveDensity, setDeviceDensity } from './swarm-settings.svelte';
  import { panelDensity } from './panel-state';
  import { SWARM_PAGE } from './swarm-page';

  let { popout = false }: { popout?: boolean } = $props();
  const swarmOn = $derived(swarmView.view === 'swarm');

  const VIEWS: readonly SwarmView[] = ['swarm', 'lists'];
  const viewOptions = $derived<SegmentedOption[]>(VIEWS.map((view) => ({
    value: view, label: t(`cplug.huddle.swarm.view.${view}`), title: t(`cplug.huddle.swarm.view.${view}_title`),
    attrs: { 'data-huddle-swarm-view-key': view },
  })));
  const densityOptions = $derived<SegmentedOption[]>(DENSITIES.map((density) => ({
    value: density, label: t(`cplug.huddle.density.${density}`), icon: `density-${density}`,
    title: t(`cplug.huddle.swarm.density.${density}_title`), attrs: { 'data-huddle-density-key': density },
  })));

  function densityNow(): string {
    return DENSITIES.find((density) => panelDensity(density) === effectiveDensity()) ?? '';
  }
</script>

{#if !popout}
  <span class="pta" data-task-manager-swarm-view={swarmView.view}>
    <Segmented label={t('cplug.huddle.swarm.view.label')} options={viewOptions}
      bind:value={() => swarmView.view, (next) => { const view = VIEWS.find((v) => v === next); if (view) setSwarmView(view); }} />
    {#if swarmOn}
      <Segmented label={t('cplug.huddle.density.label')} options={densityOptions} iconOnly
        bind:value={densityNow, (next) => { const density = DENSITIES.find((d) => d === next); if (density) setDeviceDensity(density); }} />
    {/if}
    <IconButton label={t('cplug.huddle.swarm.settings.open')} icon="gear" variant="quiet" data-huddle-settings-page
      onclick={() => void openCplugPage('taskmanager')} />
    {#if swarmOn}
      <IconButton label={t('cplug.huddle.swarm.page.open')} tooltip={t('cplug.huddle.swarm.page.open_title')} icon="grid" variant="quiet"
        data-huddle-swarm-page onclick={() => void openCplugPage(SWARM_PAGE)} />
    {/if}
  </span>
{/if}

<style>
  @layer components {
    .pta {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      min-width: 0;
    }
  }
</style>
