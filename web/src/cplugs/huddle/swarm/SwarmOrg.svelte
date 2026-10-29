<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../../sdk';
  import { colorBook, type ColorBook } from './agent-colors.svelte';
  import { Character, type CharacterPack, DEFAULT_PACK } from './characters';
  import type { FloorItem, FloorTarget } from './floor';
  import { fitView, layoutOrg, zoomAt, ZOOM_STEP, type OrgView } from './org-layout';
  import type { SwarmTree } from './swarm-tree';
  import { seedOf, sizeOf, subSeeds, talkingSide, type PanelAgent } from './panel-state';
  import { backgroundFor, colorFor, markRankOf, shapeFor, stateFor, sendFor } from './node-look';
  import NodeMenu from './NodeMenu.svelte';
  import { nodeHold } from './node-menu';
  import { MachineBadge, TaskMark } from '../../sdk/ui';

  interface Props {
    tree: SwarmTree;
    agents: readonly PanelAgent[];
    now: number;
    pack?: CharacterPack;
    colors?: ColorBook;
    still?: boolean;
    busy?: string | null;
    onOpen: (target: FloorTarget, terminal?: boolean) => void;
    foot?: Snippet;
    onFilter?: (item: FloorItem) => void;
    filtered?: string | null;
  }
  const { tree, agents, now, pack = DEFAULT_PACK, colors, still, busy = null, onOpen, foot, onFilter, filtered = null }: Props = $props();
  const book = $derived(colors ?? colorBook(agents, null));

  function pressNode(item: FloorItem, event: MouseEvent): void {
    if (onFilter && event.shiftKey) onFilter(item);
    else onOpen(item.target, event.shiftKey);
  }

  function key(item: FloorItem, event: KeyboardEvent): void {
    if (!onFilter || event.key !== 'Enter' || !event.shiftKey) return;
    event.preventDefault();
    onFilter(item);
  }

  let boxW = $state(0);
  const layout = $derived(layoutOrg(tree, boxW > 0 ? boxW : Number.POSITIVE_INFINITY));
  let box = $state<HTMLDivElement | null>(null);
  let view = $state<OrgView>({ x: 0, y: 0, k: 1 });
  let drag: { id: number; x: number; y: number; vx: number; vy: number } | null = null;

  function fit(): void {
    view = fitView(layout, box?.clientWidth ?? 0, box?.clientHeight ?? 0);
  }

  function press(factor: number): void {
    view = zoomAt(view, factor, (box?.clientWidth ?? 0) / 2, (box?.clientHeight ?? 0) / 2);
  }

  $effect(() => {
    void layout.width;
    void layout.height;
    fit();
  });

  $effect(() => {
    if (!box) return;
    const read = (): void => { boxW = box?.clientWidth ?? 0; };
    read();
    window.addEventListener('resize', read);
    return () => window.removeEventListener('resize', read);
  });

  $effect(() => {
    const el = box;
    if (!el) return;
    const wheel = (event: WheelEvent): void => {
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      view = zoomAt(view, event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP, event.clientX - rect.left, event.clientY - rect.top);
    };
    el.addEventListener('wheel', wheel, { passive: false });
    return () => el.removeEventListener('wheel', wheel);
  });

  function down(event: PointerEvent): void {
    if (event.button !== 0 || (event.target as HTMLElement).closest('.pko-node, .pko-ctl, .pko-foot, button, a, input, select, textarea, label')) return;
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY, vx: view.x, vy: view.y };
    box?.setPointerCapture?.(event.pointerId);
  }

  function move(event: PointerEvent): void {
    if (!drag || drag.id !== event.pointerId) return;
    view = { ...view, x: drag.vx + event.clientX - drag.x, y: drag.vy + event.clientY - drag.y };
  }

  function up(event: PointerEvent): void {
    if (drag?.id === event.pointerId) drag = null;
  }
  let menu = $state<{ item: FloorItem; anchor: HTMLElement } | null>(null);
  function openMenu(item: FloorItem, anchor: HTMLElement): void {
    if (item.ordinary || item.vacant || !item.agent) return;
    menu = { item, anchor };
  }
  function contextMenu(item: FloorItem, event: MouseEvent): void {
    if (item.ordinary || item.vacant || !item.agent) return;
    event.preventDefault();
    openMenu(item, event.currentTarget as HTMLElement);
  }
</script>

<div class="pko" bind:this={box} role="application" aria-label={t('cplug.huddle.swarm.org.chart')} data-swarm-org data-swarm-zoom={view.k.toFixed(2)} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
  <div class="pko-stage" style:width="{layout.width}px" style:height="{layout.height}px"
       style:transform="translate({view.x}px, {view.y}px) scale({view.k})">
    <svg class="pko-links" width={layout.width} height={layout.height} aria-hidden="true">
      {#each layout.links as link (link.to)}
        <path class="pko-link" d={link.d} data-swarm-link={link.to} />
      {/each}
    </svg>
    {#each layout.nodes as at (at.key)}
      {@const it = (tree.nodes.get(at.key) as NonNullable<ReturnType<typeof tree.nodes.get>>).item}
      {@const agent = it.agent}
      {@const state = stateFor(it, now)}
      {@const size = sizeOf(it.rank, 'detailed')}
      <button type="button" class="pko-node" class:pko-node--leaf={at.stacked} data-swarm-node={it.key} data-swarm-rank={it.ordinary ? 'session' : it.rank} data-swarm-state={state}
              aria-busy={it.vacant && busy === it.key ? 'true' : undefined} style:left="{at.x}px" style:top="{at.y}px" style:width="{at.w}px"
              title={it.vacant ? t('cplug.huddle.swarm.seat.title', { name: it.label }) : undefined}
              aria-current={filtered === it.key ? 'true' : undefined} onclick={(e) => pressNode(it, e)} onkeydown={(e) => key(it, e)}
              oncontextmenu={(e) => contextMenu(it, e)} use:nodeHold={(el) => openMenu(it, el)}
              onmousedown={(e) => { if (onFilter && e.shiftKey) e.preventDefault(); }}>
        <span class="pko-face" style:--pko-s="{size}px">
          {#if agent}
            <Character {state} {size} seed={seedOf(agent)} color={colorFor(book, it)} subs={it.ordinary ? [] : subSeeds(agent, agents)}
                       side={talkingSide(agent, agents, now)} tell={sendFor(it)} {pack} {still} rank={agent.rank} shape={shapeFor(it)} background={backgroundFor(it)} label={it.label} />
          {:else}
            <span class="pko-seat" data-swarm-roll={it.rollup} style:--pko-s="{size}px"></span>
          {/if}
        </span>
        <span class="pko-nm"><TaskMark rank={markRankOf(it)} />{it.label}<MachineBadge hostKey={agent?.host_key ?? it.row?.host_key} label={agent?.host_label ?? it.row?.host_label} state={it.row?.host_state} /></span>
      </button>
    {/each}
  </div>
  {#if foot}<div class="pko-foot" data-swarm-org-foot>{@render foot()}</div>{/if}
  <div class="pko-ctl" role="group" aria-label={t('cplug.huddle.swarm.org.zoom')}>
    <button type="button" class="pko-key" data-swarm-zoom-in aria-label={t('cplug.huddle.swarm.org.zoom_in')} onclick={() => press(ZOOM_STEP)}>+</button>
    <button type="button" class="pko-key" data-swarm-zoom-out aria-label={t('cplug.huddle.swarm.org.zoom_out')} onclick={() => press(1 / ZOOM_STEP)}>-</button>
    <button type="button" class="pko-key" data-swarm-zoom-fit onclick={fit}>{t('cplug.huddle.swarm.org.fit')}</button>
  </div>
</div>

{#if menu?.item.agent}
  <NodeMenu agent={menu.item.agent} label={menu.item.label} anchor={menu.anchor} onClose={() => (menu = null)} />
{/if}

<style>
  @layer components {
    .pko {
      position: relative;
      height: min(70vh, 640px);
      min-height: 320px;
      overflow: hidden;
      border: 1px solid var(--oc-line-rule);
      border-radius: 2px;
      background: var(--oc-ground-panel);
      cursor: grab;
      touch-action: none;
      font-family: var(--font-mono);
    }

    .pko:active {
      cursor: grabbing;
    }

    .pko-stage {
      position: absolute;
      top: 0;
      left: 0;
      transform-origin: 0 0;
    }

    .pko-links {
      position: absolute;
      inset: 0;
      overflow: visible;
      pointer-events: none;
    }

    .pko-link {
      fill: none;
      stroke: var(--oc-cyan);
      stroke-width: 1.5;
    }

    .pko-node {
      position: absolute;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
      padding: 0;
      border: 1px solid transparent;
      border-radius: 2px;
      background: none;
      color: var(--oc-text-secondary);
      font: inherit;
      transform: translate(-50%, -50%);
      cursor: pointer;
    }

    .pko-node--leaf {
      flex-direction: row;
      justify-content: flex-start;
      gap: 8px;
    }

    .pko-node--leaf .pko-nm {
      flex: 1;
      min-width: 0;
      text-align: left;
    }

    /* border: */
    .pko-node[aria-current='true'] {
      border-color: color-mix(in oklab, currentColor var(--oc-focus-keep, 75%), var(--oc-focus-lift, currentColor));
    }

    .pko-node:hover .pko-nm {
      color: var(--oc-text-bright);
    }

    .pko-face {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: var(--pko-s);
      min-height: var(--pko-s);
    }

    .pko-seat {
      width: var(--pko-s);
      height: var(--pko-s);
      border: 1px dashed var(--oc-line-rule);
      border-radius: 2px;
    }

    .pko-nm {
      max-width: 100%;
      overflow: hidden;
      font-size: var(--oc-fs-micro);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .pko-foot {
      position: absolute;
      bottom: 8px;
      left: 12px;
    }

    .pko-ctl {
      position: absolute;
      top: 8px;
      right: 8px;
      display: inline-flex;
      height: 20px;
      border: 1px solid var(--oc-line-rule);
      border-radius: 2px;
      background: var(--oc-ground-panel);
    }

    .pko-key {
      --_bd: transparent;
      min-width: 20px;
      padding: 0 6px;
      border: 1px solid var(--_bd);
      background: none;
      color: var(--oc-text-muted);
      font: inherit;
      font-size: var(--oc-fs-micro);
      line-height: 16px;
      cursor: pointer;
    }

    .pko-key + .pko-key {
      box-shadow: inset 1px 0 0 var(--oc-line-rule);
    }

    .pko-key:hover {
      color: var(--oc-text-bright);
    }
  }
</style>
