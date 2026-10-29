<script lang="ts">
  import { getContext } from 'svelte';
  import { Icon } from '../sdk/ui';
  import { BODY_OPTIONS, DEFAULT_BODY_OPTIONS, type BodyOptions } from './task-manager-body-options';
  import { t } from '../sdk';
  import { AGGREGATE, ALL_LIST, isApproved, listFallback, moveTargets, type HuddleItem } from './huddle-model';
  import { huddle, moveToList, setBackBurner } from './huddle.svelte';
  import { groupsOf, setItemGroup } from './task-manager-groups.svelte';
  import { requestEdit } from './task-manager-edit-request.svelte';
  import { openScheduleEditor } from './task-manager-schedule-editor.svelte';
  import { openFork } from './task-manager-fork.svelte';

  const WIDTH = 216;
  const HEIGHT = 240;
  const EDGE = 8;

  let { item }: { item: HuddleItem } = $props();

  const options: Readonly<BodyOptions> = getContext<BodyOptions | undefined>(BODY_OPTIONS) ?? DEFAULT_BODY_OPTIONS;
  const keyIcon = options.drawerIcons ? { size: 14, stroke: 2 } : { size: 12, stroke: undefined };

  let picking = $state(false);
  let key = $state<HTMLButtonElement | null>(null);
  let panel = $state<HTMLElement | null>(null);
  let box = $state({ left: 0, top: 0 });

  const rows = $derived(huddle.lists.filter((row) => row.key !== AGGREGATE));
  const others = $derived(moveTargets(huddle.lists, item.list));
  const current = $derived(item.group ?? null);

  const parked = $derived(item.state === 'todo');

  async function toggleBackBurner(): Promise<void> {
    close();
    await setBackBurner(item, !parked);
  }

  function openEditor(which: 'schedule' | 'title'): void {
    close();
    if (which === 'schedule') openScheduleEditor(item.list, item);
    else requestEdit(which, item.id);
  }

  function openForkDialog(): void {
    close();
    openFork(item);
  }

  function nameOf(listKey: string, name: string | null): string {
    if (listKey === ALL_LIST) return t('cplug.huddle.list.shared');
    if (name) return name;
    const fallback = listFallback(listKey);
    return t(fallback.key, { id: fallback.id });
  }

  function place(): void {
    if (!key || typeof window === 'undefined') return;
    const rect = key.getBoundingClientRect();
    box = {
      left: Math.max(EDGE, Math.min(rect.right - WIDTH, window.innerWidth - WIDTH - EDGE)),
      top: Math.max(EDGE, Math.min(rect.bottom + 4, window.innerHeight - HEIGHT - EDGE)),
    };
  }

  function close(): void {
    picking = false;
    key?.focus();
  }

  async function choose(listKey: string): Promise<void> {
    close();
    if (listKey === item.list) await setItemGroup(item, null);
    else await moveToList(item, listKey);
  }

  async function chooseGroup(listKey: string, group: number): Promise<void> {
    close();
    if (listKey === item.list) await setItemGroup(item, group);
    else await moveToList(item, listKey, group);
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const items = panel ? [...panel.querySelectorAll<HTMLElement>('[role^="menuitem"]:not(:disabled)')] : [];
    if (!items.length) return;
    const at = items.findIndex((one) => one === document.activeElement);
    const step = event.key === 'ArrowDown' ? 1 : -1;
    items[(at + step + items.length) % items.length]?.focus();
  }

  function onOutside(event: PointerEvent): void {
    if (!picking) return;
    const target = event.target as Node | null;
    if (!target || panel?.contains(target) || key?.contains(target)) return;
    picking = false;
  }

  $effect(() => {
    if (!picking) return;
    place();
    if (panel && typeof panel.showPopover === 'function' && !panel.matches(':popover-open')) panel.showPopover();
    panel?.querySelector<HTMLElement>('[role^="menuitem"]:not(:disabled)')?.focus();
  });
</script>

<svelte:window onpointerdown={onOutside} onresize={place} />

<span class="hdm">
  <button bind:this={key} type="button" class="oc-ibtn oc-ibtn--bare tkm-key" data-task-manager-move-open={item.id} aria-haspopup="menu" aria-expanded={picking}
          aria-label={t('cplug.huddle.move.button', { text: item.text })} title={t('cplug.huddle.move.title')}
          onclick={() => (picking = !picking)}><Icon name="arrow" size={keyIcon.size} strokeWidth={keyIcon.stroke} /></button>
  {#if picking}
    <div bind:this={panel} class="hdm-menu popup-focus" popover="manual" role="menu" aria-label={t('cplug.huddle.move.title')} tabindex="-1"
         style={`left: ${Math.round(box.left)}px; top: ${Math.round(box.top)}px`} onkeydown={onKeydown} data-task-manager-move-pick={item.id}>
      <span class="hdm-label" role="presentation">{t('cplug.huddle.move.title')}</span>
      {#each rows as row (row.key)}
        {#if row.key === item.list && current === null}
          <button type="button" class="hdm-item hdm-item--here" role="menuitemradio" aria-checked="true" disabled data-task-manager-move-here={row.key}
                  title={nameOf(row.key, row.name)}><span class="hdm-name">{nameOf(row.key, row.name)}</span><Icon name="check" size={12} /></button>
        {:else}
          <button type="button" class="hdm-item" role="menuitemradio" aria-checked="false" data-task-manager-move-to={row.key}
                  title={nameOf(row.key, row.name)} onclick={() => void choose(row.key)}><span class="hdm-name">{nameOf(row.key, row.name)}</span></button>
        {/if}
        {#each groupsOf(row.key) as group (group.id)}
          {#if row.key === item.list && group.id === current}
            <button type="button" class="hdm-item hdm-item--group hdm-item--here" role="menuitemradio" aria-checked="true" disabled
                    data-task-manager-move-here-group={group.id} title={group.name}><span class="hdm-name">{group.name}</span><Icon name="check" size={12} /></button>
          {:else}
            <button type="button" class="hdm-item hdm-item--group" role="menuitemradio" aria-checked="false" data-task-manager-move-group={group.id}
                    title={group.name} onclick={() => void chooseGroup(row.key, group.id)}><span class="hdm-name">{group.name}</span></button>
          {/if}
        {/each}
      {/each}
      <button type="button" class="hdm-item" role="menuitem" data-task-manager-back-burner={item.id} onclick={() => void toggleBackBurner()}>
        <span class="hdm-name">{t(parked ? 'cplug.huddle.move.take_off_back_burner' : 'cplug.huddle.move.back_burner')}</span><Icon name="status-back-burner" size={12} /></button>
      {#if !isApproved(item.state)}
        <button type="button" class="hdm-item" role="menuitem" data-task-manager-menu-schedule={item.id} onclick={() => openEditor('schedule')}>
          <span class="hdm-name">{t('cplug.huddle.move.schedule')}</span><Icon name="status-scheduled" size={12} /></button>
      {/if}
      <button type="button" class="hdm-item" role="menuitem" data-task-manager-menu-fork={item.id} onclick={openForkDialog}>
        <span class="hdm-name">{t('cplug.huddle.move.fork')}</span></button>
      <button type="button" class="hdm-item" role="menuitem" data-task-manager-menu-title={item.id} onclick={() => openEditor('title')}>
        <span class="hdm-name">{t('cplug.huddle.move.title_edit')}</span></button>
    </div>
  {/if}
</span>

<style>
  @layer components {
    .hdm {
      display: inline-flex;
    }

    .hdm-menu {
      position: fixed;
      inset: auto;
      margin: 0;
      z-index: 50;
      display: flex;
      flex-direction: column;
      width: 216px;
      max-height: 240px;
      overflow-x: hidden;
      overflow-y: auto;
      padding: var(--oc-space-1);
      border-radius: var(--oc-radius-sm);
    }

    .hdm-label {
      padding: var(--oc-space-1) var(--oc-space-2);
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label, 0.6px);
      text-transform: uppercase;
    }

    .hdm-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--oc-space-2);
      padding: 6px var(--oc-space-2);
      background: none;
      border: 0;
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font: inherit;
      font-size: var(--oc-fs-label);
      text-align: left;
      cursor: pointer;
    }

    .hdm-item--group {
      padding-left: calc(var(--oc-space-2) + 12px);
    }

    .hdm-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdm-item:hover,
    .hdm-item:focus-visible {
      background: var(--oc-ground-hover);
      color: var(--oc-text-bright);
    }

    .hdm-item--here,
    .hdm-item--here:disabled {
      color: var(--oc-orange);
      cursor: default;
    }

    .hdm-item--here:hover {
      background: transparent;
    }

    @media (max-width: 1023px) and (pointer: coarse) {
      .hdm-item {
        min-height: var(--oc-tap);
      }
    }
  }
</style>
