<script lang="ts">
  import { t } from '../sdk';
  import { Icon } from '../sdk/ui';
  import { taskManagerPrefs } from './task-manager-prefs.svelte';
  import { countBadges, hiddenSections, setCountsHidden, setSectionHidden } from './task-manager-status-folds.svelte';
  import { SECTION_ICON, SECTION_ICON_COLOR, filterChips, sectionKey, type TaskManagerSectionKey } from './task-manager-status-sections';
  import type { HuddleItem } from './huddle-model';

  let { items, doneLeft = 0 }: { items: HuddleItem[]; doneLeft?: number } = $props();
  let open = $state(false);
  let wrap = $state<HTMLElement | null>(null);
  const chips = $derived(filterChips(items, taskManagerPrefs.hideCompleted, hiddenSections.keys, { done: doneLeft }));
  const filtered = $derived(hiddenSections.keys.length > 0);
  const waiting = $derived(chips.reduce((n, c) => n + (c.needs ? c.count : 0), 0));

  $effect(() => {
    if (!open) return;
    const away = (event: Event): void => { if (wrap && !wrap.contains(event.target as Node)) open = false; };
    const esc = (event: KeyboardEvent): void => { if (event.key === 'Escape') open = false; };
    document.addEventListener('pointerdown', away, true);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('pointerdown', away, true); document.removeEventListener('keydown', esc); };
  });

  function titleOf(chip: { key: TaskManagerSectionKey; count: number; hidden: boolean; needs: boolean }): string {
    const name = t(sectionKey(chip.key));
    if (chip.needs) return t('cplug.huddle.filter.needs_title', { name, count: chip.count });
    return t(chip.hidden ? 'cplug.huddle.filter.show_title' : 'cplug.huddle.filter.hide_title', { name, count: chip.count });
  }
  const eyeTitle = $derived(t(countBadges.hidden ? 'cplug.huddle.filter.counts_show' : 'cplug.huddle.filter.counts_hide'));
  const keyTitle = $derived(waiting > 0 ? t('cplug.huddle.filter.key_needs', { count: waiting }) : t(filtered ? 'cplug.huddle.filter.key_active' : 'cplug.huddle.filter.key'));
</script>

{#if chips.length > 0}
<span class="hdf-end">
<span class="hdf" bind:this={wrap} data-task-manager-status-filter>
  <div class="hdf-card popup-focus" role="group" aria-label={t('cplug.huddle.filter.label')} aria-hidden={!open}
       data-open={open ? 'on' : 'off'} data-task-manager-filter-card>
    {#each chips as chip (chip.key)}
      <button type="button" class="hdf-key" aria-pressed={!chip.hidden} data-task-manager-filter-key={chip.key} tabindex={open ? 0 : -1}
              data-task-manager-filter-needs={chip.needs ? 'on' : undefined} aria-label={titleOf(chip)} title={titleOf(chip)}
              style:--_mark={SECTION_ICON_COLOR[chip.key]} onclick={() => setSectionHidden(chip.key, !chip.hidden)}>
        <Icon name={SECTION_ICON[chip.key]} size={12} strokeWidth={1.75} />
        {#if chip.needs}<span class="hdf-needs" aria-hidden="true">!</span>{/if}
      </button>
    {/each}
  </div>
  <button type="button" class="hdf-toggle" aria-expanded={open} aria-label={keyTitle} title={keyTitle}
          data-task-manager-filter-toggle data-task-manager-filter-state={filtered ? 'filtered' : 'all'} onclick={() => (open = !open)}>
    <Icon name="funnel" size={14} strokeWidth={1.75} />
    {#if waiting > 0}<span class="hdf-needs" aria-hidden="true">!</span>{/if}
  </button>
</span>
<button type="button" class="hdf-toggle" aria-pressed={!countBadges.hidden} aria-label={eyeTitle} title={eyeTitle}
        data-task-manager-counts-toggle data-task-manager-counts-state={countBadges.hidden ? 'hidden' : 'shown'} onclick={() => setCountsHidden(!countBadges.hidden)}>
  <Icon name={countBadges.hidden ? 'eye-off' : 'eye'} size={14} strokeWidth={1.75} />
</button>
</span>
{/if}

<style>
  @layer components {
    .hdf-end {
      display: inline-flex;
      flex: none;
      align-items: center;
      align-self: stretch;
      margin-left: auto;
    }

    .hdf {
      position: relative;
      display: inline-flex;
      flex: none;
      align-items: center;
      align-self: stretch;
    }

    .hdf-toggle {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      padding: 0;
      border: 0;
      background: none;
      color: var(--oc-text-dim);
      cursor: pointer;
    }

    .hdf-toggle[data-task-manager-filter-state='filtered'] {
      color: var(--oc-cyan);
    }

    .hdf-toggle:hover {
      color: var(--oc-text-bright);
    }

    .hdf-card {
      position: absolute;
      top: 0;
      right: 100%;
      bottom: 0;
      z-index: 7;
      display: flex;
      flex-wrap: nowrap;
      align-items: center;
      gap: 3px;
      box-sizing: border-box;
      max-width: calc(100vw - 56px);
      padding: 0 8px;
      overflow-x: auto;
      overflow-y: hidden;
      border-radius: var(--oc-radius-sm);
      transform: scaleX(0);
      transform-origin: right center;
      visibility: hidden;
      pointer-events: none;
      transition: transform 0.14s ease-out, visibility 0s linear 0.14s;
    }

    .hdf-card:not([data-open='on']) { animation: none; }

    .hdf-card[data-open='on'] {
      transform: scaleX(1);
      visibility: visible;
      pointer-events: auto;
      transition: transform 0.14s ease-out, visibility 0s;
    }

    @media (prefers-reduced-motion: reduce) {
      .hdf-card,
      .hdf-card[data-open='on'] { transition: none; }
    }

    .hdf-key {
      position: relative;
      flex: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 16px;
      height: 18px;
      padding: 0;
      border: 0;
      background: none;
      color: var(--_mark, var(--oc-text-muted));
      cursor: pointer;
    }

    .hdf-key[aria-pressed='false'] {
      color: var(--oc-text-dim);
      opacity: 0.5;
    }

    .hdf-key[aria-pressed='false']::after {
      content: '';
      position: absolute;
      left: 1px;
      right: 1px;
      top: 50%;
      height: 1px;
      background: currentColor;
      transform: rotate(-35deg);
    }

    .hdf-key:hover {
      color: var(--oc-text-bright);
    }

    .hdf-key[data-task-manager-filter-needs='on'] {
      opacity: 1;
    }

    .hdf-needs {
      position: absolute;
      top: -2px;
      right: -1px;
      color: var(--oc-coral);
      font-size: 9px;
      font-weight: 700;
      line-height: 1;
    }
  }
</style>
