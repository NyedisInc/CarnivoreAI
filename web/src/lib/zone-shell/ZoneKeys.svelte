<script lang="ts">
  import { halveAt, percent, sectionStyle } from '../session-rail/rail-cuts';
  import { cutBounds, centreOf } from '../session-rail/rail-cuts';
  import { RAIL_RATIO_STEP } from '../session-rail/rail-model';
  import { t } from '../i18n/index.svelte';
  import SplitDivider from '../split-divider/SplitDivider.svelte';
  import TabKey from './TabKey.svelte';
  import EditCell from './EditCell.svelte';
  import { nextKey } from './key-nav';
  import { edgeFade, type EdgeFade } from './strip-edge-fade';
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
    motion = null,
    oncut,
    oncutsave,
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
    ondragstart?: (event: PointerEvent, key: string, title: string) => void;
    hiddenKey?: (key: string) => boolean;
    ontoggle?: (key: string, hide: boolean) => void;
    oncut?: (index: number, value: number) => void;
    oncutsave?: () => void;
    motion?: { cell(node: HTMLElement, key: string): { update?(key: string): void; destroy?(): void } | void } | null;
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
    if (motion && event.key.startsWith('Arrow')) return;
    if (editing) onedit(event, key, title);
    else roving(event, key);
  }

  $effect(() => {
    if (!motion || !root) return;
    const strip = root;
    /* with a plain */
    const walkWithArrows = (event: KeyboardEvent): void => {
      if (editing || event.altKey || !event.key.startsWith('Arrow')) return;
      const key = (event.target as Element).closest<HTMLElement>('[data-zone-item]')?.dataset['zoneItem'];
      if (!key) return;
      roving(event, key);
      event.stopPropagation();
    };
    strip.addEventListener('keydown', walkWithArrows, true);
    return () => strip.removeEventListener('keydown', walkWithArrows, true);
  });

  let fade = $state<EdgeFade>(null);

  $effect(() => {
    if (!root || flow) return;
    const strip = root;
    const measure = (): void => {
      fade = axis === 'x' ? edgeFade(strip.scrollLeft, strip.clientWidth, strip.scrollWidth) : edgeFade(strip.scrollTop, strip.clientHeight, strip.scrollHeight);
    };
    measure();
    strip.addEventListener('scroll', measure, { passive: true });
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    observer?.observe(strip);
    for (const keys of strip.querySelectorAll('[data-rail-keys], .rail__cell')) observer?.observe(keys);
    return () => {
      strip.removeEventListener('scroll', measure);
      observer?.disconnect();
    };
  });

  function cellAction(node: HTMLElement, key: string): { update?(key: string): void; destroy?(): void } | void {
    return motion?.cell(node, key);
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
          ondragstart={ondragstart ? (event, key) => ondragstart(event, key, look.title) : undefined}
        />
{/snippet}

<div class="rail__sections" data-motion={motion ? '' : undefined} data-rail-sections data-axis={axis} data-editing={editing} data-flow={flow ? '' : undefined} data-fade={fade} bind:this={root}>
  {#each zones as zone, s (s)}
    {@const tabs = zone.tabs}
    {@const lifted = tabs.filter((tab) => tab.key !== carriedKey)}
    <div class="rail__keys" data-rail-keys data-rail-section={s} data-rail-pin-end={s === lastZone && ghostAfter !== lastZone ? 'true' : undefined} style={flow ? undefined : sectionStyle(axis, areaOf(s), shownCuts)}>
      {#each tabs as tab, i (tab.key)}
        {@const look = face(tab)}
        {@const gone = !motion && tab.key === carriedKey}
        {#if editing && !motion && !gone && mark?.section === s && mark.index === lifted.indexOf(tab)}<div class="rail__slot" data-zone-mark></div>{/if}
        
        <span class="rail__cell" data-motion={motion ? '' : undefined} data-motion-grab={motion ? '' : undefined} data-carried={gone ? '' : undefined} use:cellAction={tab.key}>
          {#if editing && ontoggle}
            <EditCell hidden={hiddenKey?.(tab.key) ?? false} name={look.title} ontoggle={() => ontoggle(tab.key, !(hiddenKey?.(tab.key) ?? false))}>
              {@render keyOf(tab, look, zone)}
            </EditCell>
          {:else}
            {@render keyOf(tab, look, zone)}
          {/if}
        </span>
      {/each}
      {#if editing && !motion && mark?.index === lifted.length && mark.section === s && tabs.length > 0}<div class="rail__slot" data-zone-mark></div>{/if}
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
      
      {#if oncut && !editing}
        <SplitDivider {axis} ratio={cut} min={cutBounds(shownCuts, c).min} max={cutBounds(shownCuts, c).max} step={RAIL_RATIO_STEP} reset={centreOf(shownCuts, c)}
          label={t(axis === 'y' ? 'session_rail.divider' : 'session_rail.divider_bottom')} onpreview={(next) => oncut(c, next)} oncommit={() => oncutsave?.()} />
      {/if}
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

    .rail__cell[data-motion] {
      display: block;
    }

    .rail__sections[data-motion] {
      overflow-x: hidden;
      overflow-y: auto;
      scrollbar-width: none;
    }

    .rail__sections[data-motion][data-axis='x'] {
      overflow-x: auto;
      overflow-y: hidden;
    }

    .rail__sections[data-motion]::-webkit-scrollbar {
      display: none;
    }

    .rail__sections[data-fade='start'] {
      mask-image: linear-gradient(to bottom, transparent, var(--oc-mask-solid) var(--oc-space-5));
    }

    .rail__sections[data-fade='end'] {
      mask-image: linear-gradient(to top, transparent, var(--oc-mask-solid) var(--oc-space-5));
    }

    .rail__sections[data-fade='both'] {
      mask-image: linear-gradient(to bottom, transparent, var(--oc-mask-solid) var(--oc-space-5), var(--oc-mask-solid) calc(100% - var(--oc-space-5)), transparent);
    }

    .rail__sections[data-axis='x'][data-fade='start'] {
      mask-image: linear-gradient(to right, transparent, var(--oc-mask-solid) var(--oc-space-5));
    }

    .rail__sections[data-axis='x'][data-fade='end'] {
      mask-image: linear-gradient(to left, transparent, var(--oc-mask-solid) var(--oc-space-5));
    }

    .rail__sections[data-axis='x'][data-fade='both'] {
      mask-image: linear-gradient(to right, transparent, var(--oc-mask-solid) var(--oc-space-5), var(--oc-mask-solid) calc(100% - var(--oc-space-5)), transparent);
    }

    .rail__sections[data-motion] .rail__keys {
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
      height: var(--oc-grip-line);
      background: var(--oc-line-frame);
      pointer-events: none;
    }

    [data-axis='x'] .rail__split {
      top: 0;
      bottom: 0;
      right: auto;
      width: var(--oc-grip-line);
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
