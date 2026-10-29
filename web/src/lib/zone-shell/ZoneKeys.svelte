<script lang="ts">
  import { sectionStyle, splitAt } from '../session-rail/rail-sections';
  import TabKey from './TabKey.svelte';
  import EditCell from './EditCell.svelte';
  import { nextKey } from './key-nav';
  import type { Zone } from './zone.svelte';
  import type { KeyFace, TabRef } from './zone-types';

  let {
    zones,
    axis,
    ratio,
    labelAt,
    iconPx,
    compact,
    editing,
    openKeys,
    face,
    mark,
    empty,
    flow = false,
    toggle = false,
    home = null,
    onpress,
    onedit,
    ondragstart,
    hiddenKey,
    ontoggle,
  }: {
    zones: readonly Zone[];
    axis: 'x' | 'y';
    ratio: number;
    labelAt: string;
    iconPx: number;
    compact: boolean;
    editing: boolean;
    openKeys: ReadonlySet<string>;
    face: (tab: TabRef) => KeyFace;
    mark: { section: number | null; index: number } | null;
    empty: string | null;
    flow?: boolean;
    toggle?: boolean;
    home?: string | null;
    onpress: (zone: Zone, key: string) => void;
    onedit: (event: KeyboardEvent, key: string, title: string) => void;
    ondragstart: (event: PointerEvent, key: string, title: string) => void;
    hiddenKey?: (key: string) => boolean;
    ontoggle?: (key: string, hide: boolean) => void;
  } = $props();

  let root = $state<HTMLElement | null>(null);
  let stop = $state<string | null>(null);

  const split = $derived(zones.length > 1);
  const allKeys = $derived(zones.flatMap((zone) => zone.tabs.map((tab) => tab.key)));
  const tabbable = (key: string): boolean => {
    if (stop !== null && allKeys.includes(stop)) return stop === key;
    return (home !== null && allKeys.includes(home) ? home : allKeys[0]) === key;
  };

  function roving(event: KeyboardEvent, key: string): void {
    const next = nextKey(event.key, allKeys, key, axis, false);
    if (next === null) return;
    event.preventDefault();
    stop = next;
    for (const item of root?.querySelectorAll<HTMLElement>('[data-zone-item]') ?? []) if (item.dataset['zoneItem'] === next) item.focus();
  }

  function keydown(event: KeyboardEvent, key: string, title: string): void {
    if (editing) onedit(event, key, title);
    else roving(event, key);
  }
</script>

{#snippet keyOf(tab: TabRef, look: KeyFace, zone: Zone)}
        <TabKey
          id={tab.key}
          variant="bar"
          face={look}
          {iconPx}
          {labelAt}
          {compact}
          quiet={editing}
          state={editing ? null : toggle ? 'pressed' : 'expanded'}
          active={openKeys.has(tab.key)}
          tabbable={editing || tabbable(tab.key)}
          onpress={(key) => onpress(zone, key)}
          onfocus={(key) => (stop = key)}
          onkey={(event, key) => keydown(event, key, look.title)}
          onmenu={zone.spec.openMenu ? (key, anchor) => zone.openMenu(key, anchor) : undefined}
          ondragstart={(event, key) => ondragstart(event, key, look.title)}
        />
{/snippet}

<div class="rail__sections" data-rail-sections data-axis={axis} data-editing={editing} data-flow={flow ? '' : undefined} bind:this={root}>
  {#each zones as zone, s (s)}
    {@const tabs = zone.tabs}
    <div class="rail__keys" data-rail-keys data-rail-section={s} data-rail-pin-end={s === zones.length - 1 ? 'true' : undefined} style={flow ? undefined : sectionStyle(axis, s, zones.length, ratio)}>
      {#each tabs as tab, i (tab.key)}
        {@const look = face(tab)}
        {#if editing && mark?.index === i && mark.section === s}<div class="rail__mark" data-zone-mark></div>{/if}
        {#if editing && ontoggle}
          <EditCell hidden={hiddenKey?.(tab.key) ?? false} name={look.title} ontoggle={() => ontoggle(tab.key, !(hiddenKey?.(tab.key) ?? false))}>
            {@render keyOf(tab, look, zone)}
          </EditCell>
        {:else}
          {@render keyOf(tab, look, zone)}
        {/if}
      {/each}
      {#if editing && mark?.index === tabs.length && mark.section === s && tabs.length > 0}<div class="rail__mark" data-zone-mark></div>{/if}
      {#if empty}
        <p class="rail__empty" data-rail-empty>{empty}</p>
      {/if}
    </div>
  {/each}
  {#if split && !flow}
    <div class="rail__split" data-rail-split={splitAt(ratio)} style={axis === 'x' ? `left: ${splitAt(ratio)}` : `top: ${splitAt(ratio)}`}></div>
  {/if}
</div>

<style>
  @layer components {
    .rail__sections {
      position: relative;
      flex: 1 1 auto;
      min-width: 0;
      min-height: 0;
    }

    .rail__keys {
      position: absolute;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--rail-gap, var(--oc-space-1));
      min-width: 0;
      min-height: 0;
      padding: var(--rail-pad, var(--oc-space-2)) 0;
      overflow-x: hidden;
      overflow-y: auto;
      scrollbar-width: thin;
    }

    [data-axis='x'] .rail__keys {
      flex-direction: row;
      padding: 0 var(--rail-pad, var(--oc-space-2));
      overflow-x: auto;
      overflow-y: hidden;
    }

    .rail__sections[data-flow] {
      flex: 0 0 auto;
    }

    .rail__sections[data-flow] .rail__keys {
      position: static;
      padding: 0;
      overflow: visible;
    }

    .rail__keys[data-rail-pin-end='true'] {
      padding-bottom: calc(var(--rail-pad, var(--oc-space-2)) + var(--rail-pin-slot, 0px));
    }

    [data-axis='x'] .rail__keys[data-rail-pin-end='true'] {
      padding-bottom: 0;
      padding-right: calc(var(--rail-pad, var(--oc-space-2)) + var(--rail-pin-slot, 0px));
    }

    .rail__split {
      position: absolute;
      left: 0;
      right: 0;
      height: 2px;
      background: var(--oc-line-frame);
      pointer-events: none;
    }

    [data-axis='x'] .rail__split {
      top: 0;
      bottom: 0;
      right: auto;
      width: 2px;
      height: auto;
    }

    .rail__mark {
      flex: none;
      width: 24px;
      height: 2px;
      background: var(--oc-orange);
    }

    [data-axis='x'] .rail__mark {
      width: 2px;
      height: 24px;
    }

    .rail__empty {
      margin: 0;
      color: var(--oc-text-dim);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro, 10px);
      text-align: center;
      white-space: nowrap;
      writing-mode: vertical-rl;
    }

    [data-axis='x'] .rail__empty {
      writing-mode: horizontal-tb;
    }
  }
</style>
