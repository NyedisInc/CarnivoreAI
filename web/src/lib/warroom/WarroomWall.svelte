<script lang="ts">
  import { wakeOrPick } from '../../opscenter/api';
  import { selectBrowserItem } from '../browser/select-push.svelte';
  import { relative } from '../../opscenter/lib/format';
  import { t } from '../i18n/index.svelte';
  import WarroomTile from './WarroomTile.svelte';
  import WarroomCard from './WarroomCard.svelte';
  import { openWarroomModal } from './modal';
  import { projectColorVar } from '../project-colors/palette';
  import { gridDims, outlineEdges, peekRange, peekScale, peekTransform, peekWidth as peekPx, PEEK_DELAY_MS, wallCells, type PeekRange } from './wall-layout';
  import type { AsleepTile, TileGroup } from './warroom-model';
  import './warroom.css';

  let { groups, peekWidth, range = $bindable() }: { groups: readonly TileGroup[]; peekWidth: number; range?: PeekRange } = $props();

  let root = $state<HTMLDivElement | null>(null);
  let fill = $state<HTMLDivElement | null>(null);
  let box = $state({ w: 0, h: 0 });
  const cells = $derived(wallCells(groups));
  const dims = $derived(gridDims(cells.length, box.w, box.h));
  $effect(() => {
    range = peekRange({ width: box.w, height: box.h }, { width: dims.cellW, height: dims.cellH });
  });
  const edges = $derived(outlineEdges(cells.map((c) => c.group), dims.cols));

  $effect(() => {
    const parent = fill;
    if (!parent) return;
    const measure = (): void => {
      box = { w: parent.clientWidth, h: parent.clientHeight };
    };
    measure();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const RO = (globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver;
    const observer = typeof RO === 'function' ? new RO(() => { clearTimeout(timer); timer = setTimeout(measure, 80); }) : null;
    observer?.observe(parent);
    return () => {
      clearTimeout(timer);
      observer?.disconnect();
    };
  });

  function peek(cell: HTMLElement): void {
    const tile = cell.firstElementChild as HTMLElement | null;
    const scroller = fill?.parentElement;
    if (!tile || !scroller) return;
    const at = cell.getBoundingClientRect();
    const sc = scroller.getBoundingClientRect();
    const view = globalThis.window;
    const left = Math.max(sc.left, 0);
    const top = Math.max(sc.top, 0);
    const right = Math.min(sc.right, view.innerWidth);
    const bottom = Math.min(sc.bottom, view.innerHeight);
    const wanted = peekScale({ width: at.width, height: at.height }, { width: box.w, height: box.h }, peekPx(box.w, peekWidth));
    const p = peekTransform(
      { left: at.left, top: at.top, width: at.width, height: at.height },
      { left, top, width: right - left, height: bottom - top },
      wanted,
    );
    tile.style.setProperty('--ww-s', String(p.scale));
    tile.style.setProperty('--ww-dx', `${p.dx}px`);
    tile.style.setProperty('--ww-dy', `${p.dy}px`);
  }

  let peeking: HTMLElement | null = null;
  let pending: ReturnType<typeof setTimeout> | undefined;

  function unpeek(): void {
    clearTimeout(pending);
    pending = undefined;
    peeking?.firstElementChild?.removeAttribute('data-wr-zoomed');
    peeking = null;
  }

  function startPeek(cell: HTMLElement, now = false): void {
    unpeek();
    peek(cell);
    const run = (): void => {
      pending = undefined;
      if (!cell.isConnected) return;
      peek(cell);
      cell.firstElementChild?.setAttribute('data-wr-zoomed', '');
      peeking = cell;
    };
    if (now) run();
    else pending = setTimeout(run, PEEK_DELAY_MS);
  }

  $effect(() => unpeek);

  $effect(() => {
    void peekWidth;
    void box;
    const cell = root?.querySelector<HTMLElement>('.ww-cell:hover, .ww-cell:focus-within');
    if (cell) peek(cell);
  });

  function lastActive(tile: AsleepTile): string {
    const at = tile.lastActive ? Date.parse(tile.lastActive) : NaN;
    return Number.isNaN(at)
      ? t('warroom.tile.never')
      : t('warroom.tile.last_active', { when: relative((Date.now() - at) / 60000) });
  }

  function wake(tile: AsleepTile): void {
    void wakeOrPick(tile.record.session_uuid, tile.record.tmux_name ?? '', tile.name);
  }
</script>

<div class="ww-fill" bind:this={fill}>
<div
  class="ww"
  data-warroom-wall
  data-wr-cols={dims.cols}
  data-wr-rows={dims.rows}
  style:grid-template-columns={`repeat(${dims.cols}, minmax(0, 1fr))`}
  style:grid-template-rows={dims.scroll ? `repeat(${dims.rows}, ${dims.cellH}px)` : `repeat(${dims.rows}, minmax(0, 1fr))`}
  style:height={dims.scroll ? `${dims.rows * dims.cellH}px` : '100%'}
  bind:this={root}
>
  {#each cells as cell, at (cell.tile.key)}
    {@const tile = cell.tile}
    {@const edge = edges[at]}
    <div
      class="ww-cell"
      data-wr-group={cell.group}
      style:--ww-color={projectColorVar(cell.color)}
      style:--ww-et={edge?.top ? '2px' : '0px'}
      style:--ww-er={edge?.right ? '2px' : '0px'}
      style:--ww-eb={edge?.bottom ? '2px' : '0px'}
      style:--ww-el={edge?.left ? '2px' : '0px'}
      style:order={at}
      onpointerenter={(event) => startPeek(event.currentTarget, event.pointerType === 'touch')}
      onpointerleave={() => unpeek()}
      onfocusin={(event) => {
        if ((event.target as HTMLElement).matches(':focus-visible')) startPeek(event.currentTarget);
      }}
      onfocusout={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) unpeek();
      }}
    >
      {#if tile.kind === 'live'}
        <WarroomTile {tile} onopen={openWarroomModal} />
      {:else if tile.kind === 'asleep'}
        <WarroomCard
          kind="asleep"
          name={tile.name}
          unread={tile.record.unread === true}
          lines={[cell.label, lastActive(tile)]}
          dim
          onopen={() => wake(tile)}
        />
      {:else}
        <WarroomCard
          kind="browser"
          name={tile.name}
          lines={[tile.url, t(tile.browser.state === 'live' ? 'warroom.tile.live' : 'warroom.tile.stopped')]}
          onopen={() => selectBrowserItem(tile.browser.id)}
        />
      {/if}
      {#if cell.first}<span class="ww-plabel">{cell.label}</span>{/if}
    </div>
  {/each}
</div>
</div>
