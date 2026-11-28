<script lang="ts">
  import { t } from '../sdk';
  import { Icon } from '../sdk/ui';
  import { taskManagerPrefs, setAccordion, setDensity, setView } from './task-manager-prefs.svelte';
  import { DENSITIES } from './huddle-density';
  import type { TaskManagerViewMode } from './task-manager-status-sections';

  const VIEWS: readonly TaskManagerViewMode[] = ['status', 'area'];
  let { viewKeys = true, density = true }: { viewKeys?: boolean; density?: boolean } = $props();
  const pressed = (density: (typeof DENSITIES)[number]): boolean => taskManagerPrefs.density === density;
  const pick = (density: (typeof DENSITIES)[number]): void => void setDensity(density);
</script>

{#if viewKeys}
  <span class="hdv" role="group" aria-label={t('cplug.huddle.view.label')} data-task-manager-view={taskManagerPrefs.view}>
    {#each VIEWS as view (view)}
      <button type="button" class="hdv-key" aria-pressed={taskManagerPrefs.view === view} data-task-manager-view-key={view}
              title={t(`cplug.huddle.view.${view}_title`)} onclick={() => void setView(view)}>{t(`cplug.huddle.view.${view}`)}</button>
    {/each}
  </span>
{/if}
{#if density}
<span class="hdv hdv--density" role="group" aria-label={t('cplug.huddle.density.label')} data-task-manager-density={taskManagerPrefs.density}>
  {#each DENSITIES as density (density)}
    <button type="button" class="hdv-key hdv-key--icon" aria-pressed={pressed(density)} data-huddle-density-key={density}
            aria-label={t(`cplug.huddle.density.${density}`)} title={t(`cplug.huddle.density.${density}_title`)}
            onclick={() => pick(density)}><Icon name={`density-${density}`} size={12} /></button>
  {/each}
  <button type="button" class="hdv-key hdv-key--icon" aria-pressed={taskManagerPrefs.accordion} data-task-manager-accordion-key
          aria-label={t('cplug.huddle.accordion')} title={t('cplug.huddle.accordion_title')}
          onclick={() => void setAccordion(!taskManagerPrefs.accordion)}><Icon name="list" size={12} /></button>
</span>
{/if}

<style>
  @layer components {
    .hdv {
      display: inline-flex;
      flex: 0 1 auto;
      min-width: 0;
      max-width: 100%;
      height: 20px;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-control);
    }

    .hdv-key {
      --_bd: transparent;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      padding: 0 var(--oc-space-1-5);
      border: 1px solid var(--_bd);
      background: none;
      color: var(--oc-text-muted);
      font: inherit;
      font-size: var(--oc-fs-micro);
      line-height: 16px;
      white-space: nowrap;
      cursor: pointer;
    }

    .hdv-key + .hdv-key {
      box-shadow: inset 1px 0 0 var(--oc-line-rule);
    }

    .hdv-key:hover {
      color: var(--oc-text-bright);
    }

    .hdv-key[aria-pressed='true'] {
      color: var(--oc-orange);
    }

    .hdv--density {
      margin-left: var(--oc-space-1);
    }

    .hdv-key--icon {
      display: inline-flex;
      align-items: center;
      padding: 0 var(--oc-space-1);
    }
  }
</style>
