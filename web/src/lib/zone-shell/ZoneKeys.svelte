<script lang="ts">
  import { halveAt, percent, sectionStyle } from '../session-rail/rail-cuts';
  import TabKey from './TabKey.svelte';
  import EditCell from './EditCell.svelte';
  import { nextKey } from './key-nav';
  import type { Zone } from './zone.svelte';
  import type { KeyFace, TabRef } from './zone-types';

  let {
    zones,
    axis,
    cuts,
    ghostAfter = null,
    ghostAimed = false,
    carriedKey = null,
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
    cuts: readonly number[];
    ghostAfter?: number | null;
    ghostAimed?: boolean;
    carriedKey?: string | null;
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

  const shownCuts = $derived(ghostAfter === null ? cuts : halveAt(cuts, ghostAfter));
  const areaOf = (zone: number): number => (ghostAfter !== null && zone > ghostAfter ? zone + 1 : zone);
  const lastZone = $derived(zones.length - 1);
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
    {@const lifted = tabs.filter((tab) => tab.key !== carriedKey)}
    <div class="rail__keys" data-rail-keys data-rail-section={s} data-rail-pin-end={s === lastZone && ghostAfter !== lastZone ? 'true' : undefined} style={flow ? undefined : sectionStyle(axis, areaOf(s), shownCuts)}>
      {#each tabs as tab, i (tab.key)}
        {@const look = face(tab)}
        {@const gone = tab.key === carriedKey}
        {#if editing && !gone && mark?.section === s && mark.index === lifted.indexOf(tab)}<div class="rail__slot" data-zone-mark></div>{/if}
        
        <span class="rail__cell" data-carried={gone ? '' : undefined}>
          {#if editing && ontoggle}
            <EditCell hidden={hiddenKey?.(tab.key) ?? false} name={look.title} ontoggle={() => ontoggle(tab.key, !(hiddenKey?.(tab.key) ?? false))}>
              {@render keyOf(tab, look, zone)}
            </EditCell>
          {:else}
            {@render keyOf(tab, look, zone)}
          {/if}
        </span>
      {/each}
      {#if editing && mark?.index === lifted.length && mark.section === s && tabs.length > 0}<div class="rail__slot" data-zone-mark></div>{/if}
      {#if empty}
        <p class="rail__empty" data-rail-empty>{empty}</p>
      {/if}
    </div>
  {/each}
  {#if ghostAfter !== null && !flow}
    <div class="rail__newarea" data-rail-ghost={ghostAfter} data-aimed={ghostAimed} data-rail-pin-end={ghostAfter === lastZone ? 'true' : undefined} style={sectionStyle(axis, ghostAfter + 1, shownCuts)} aria-hidden="true">
      <div class="rail__newarea-box"></div>
    </div>
  {/if}
  {#if shownCuts.length > 0 && !flow}
    {#each shownCuts as cut, c (c)}
      <div class="rail__split" data-rail-split={percent(cut)} data-preview={ghostAfter === c ? '' : undefined} style={axis === 'x' ? `left: ${percent(cut)}` : `top: ${percent(cut)}`}></div>
    {/each}
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

    .rail__cell {
      display: contents;
    }

    .rail__cell[data-carried] {
      display: block;
      position: absolute;
      width: 0;
      height: 0;
      overflow: hidden;
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

    .rail__split[data-preview] {
      height: 0;
      background: none;
      border-top: var(--oc-border) dashed var(--oc-cyan);
    }

    [data-axis='x'] .rail__split[data-preview] {
      width: 0;
      height: auto;
      border-top: 0;
      border-left: var(--oc-border) dashed var(--oc-cyan);
    }

    .rail__slot {
      flex: none;
      box-sizing: border-box;
      width: var(--rail-key-w, 28px);
      height: var(--rail-key-h, 28px);
      min-width: var(--rail-key-minw, 0px);
      min-height: var(--rail-key-minh, 0px);
      border: var(--oc-border) dashed var(--oc-cyan);
      border-radius: var(--oc-radius-sm);
      background: color-mix(in oklab, var(--oc-cyan) 8%, transparent);
    }

    .rail__newarea {
      position: absolute;
      display: flex;
      box-sizing: border-box;
      padding: var(--rail-pad, var(--oc-space-2));
    }

    .rail__newarea[data-rail-pin-end='true'] {
      padding-bottom: calc(var(--rail-pad, var(--oc-space-2)) + var(--rail-pin-slot, 0px));
    }

    [data-axis='x'] .rail__newarea[data-rail-pin-end='true'] {
      padding-bottom: var(--rail-pad, var(--oc-space-2));
      padding-right: calc(var(--rail-pad, var(--oc-space-2)) + var(--rail-pin-slot, 0px));
    }

    .rail__newarea-box {
      flex: 1 1 auto;
      min-width: 0;
      min-height: 0;
      border: var(--oc-border) dashed var(--oc-cyan);
      border-radius: var(--oc-radius-sm);
      background: color-mix(in oklab, var(--oc-cyan) 6%, transparent);
    }

    .rail__newarea[data-aimed='true'] .rail__newarea-box {
      background: color-mix(in oklab, var(--oc-cyan) 22%, transparent);
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
