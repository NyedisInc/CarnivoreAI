<script lang="ts">
  import { truncatedTip } from '../tooltip/truncated-tip';
  import { untrack } from 'svelte';
  import { bindTerminalTheme } from '../../opscenter/cells/terminal-live/theme';
  import { visibilityObserver } from '../visibility-observer';
  import { t } from '../i18n/index.svelte';
  import SessionFace from '../sessions/SessionFace.svelte';
  import WarroomCard from './WarroomCard.svelte';
  import { snapshotStore } from './snapshot-store';
  import { peekCrop } from './wall-layout';
  import { contentExtent, measureCell, paintTile, type CellMetrics, type PaintableTerm } from './tile-canvas';
  import type { LiveTile } from './warroom-model';
  import type { SessionInfo } from '../../opscenter/api/types';

  interface Props {
    tile: LiveTile;
    onopen: (info: SessionInfo) => void;
  }
  let { tile, onopen }: Props = $props();

  const row = $derived(tile.row);
  const socketId = $derived(row.session.id);

  let el = $state<HTMLDivElement | null>(null);
  let bodyEl = $state<HTMLDivElement | null>(null);
  let canvas = $state<HTMLCanvasElement | null>(null);
  let visible = $state(visibilityObserver() === undefined);
  let hovered = $state(false);
  let gone = $state(false);
  let unsupportedId = $state<string | null>(null);
  const unsupported = $derived(unsupportedId !== null && unsupportedId === socketId);
  let olderId = $state<string | null>(null);
  const older = $derived(olderId !== null && olderId === socketId);
  let bodyWidth = $state(0);
  let bodyHeight = $state(0);
  let paneWidth = $state(0);
  let paneHeight = $state(0);
  let repaint: () => void = () => {};

  const offline = $derived(tile.offline);

  $effect(() => {
    if (offline) olderId = null;
  });

  $effect(() => {
    const node = el;
    const Ctor = visibilityObserver();
    if (!node || !Ctor) return;
    const watcher = new Ctor((entries) => {
      const last = entries[entries.length - 1];
      if (last) visible = last.isIntersecting;
    });
    watcher.observe(node);
    return () => watcher.disconnect();
  });

  $effect(() => {
    const node = bodyEl;
    if (!node) return;
    const measure = (): void => {
      bodyWidth = node.offsetWidth || 0;
      bodyHeight = node.offsetHeight || 0;
    };
    measure();
    const RO = (globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver;
    const observer = typeof RO === 'function' ? new RO(measure) : null;
    observer?.observe(node);
    return () => observer?.disconnect();
  });

  function monoFace(): string {
    const root = globalThis.document?.documentElement;
    const view = root?.ownerDocument?.defaultView;
    return root && view ? view.getComputedStyle(root).getPropertyValue('--font-mono').replace(/\s+/g, ' ').trim() : '';
  }

  const FONT_SIZE = 14;

  $effect(() => {
    const target = canvas;
    const id = socketId;
    const Term = (globalThis as { Terminal?: new (options: unknown) => unknown }).Terminal;
    if (!visible || offline || !target || !id || typeof Term !== 'function') return;
    const ctx = target.getContext('2d');
    if (!ctx) return;
    const face = monoFace();
    const term = new Term({ fontSize: FONT_SIZE, scrollback: 0, disableStdin: true, cursorBlink: false, allowProposedApi: true }) as
      PaintableTerm & { write(d: string, cb?: () => void): void; reset(): void; resize(c: number, r: number): void; dispose(): void };
    const cell: CellMetrics = measureCell(ctx, face, FONT_SIZE);
    let theme: Record<string, string> | undefined;
    const options = {
      get theme() { return theme; },
      set theme(next: Record<string, string> | undefined) { theme = next; repaint(); },
      minimumContrastRatio: 1,
    };
    repaint = (): void => {
      const isHot = el?.hasAttribute('data-wr-zoomed') ?? false;
      const peek = isHot ? Math.max(1, Number.parseFloat(el?.style.getPropertyValue('--ww-s') ?? '') || 1) : 1;
      const dpr = (globalThis.devicePixelRatio || 1) * peek;
      const boxW = untrack(() => bodyWidth);
      const boxH = untrack(() => bodyHeight);
      if (boxW <= 0 || boxH <= 0 || term.cols <= 0 || term.rows <= 0) return;
      const used = contentExtent(term.buffer.active, term.cols, term.rows);
      const crop = peekCrop({ cols: term.cols, rows: term.rows, ...used, cellW: cell.w, cellH: cell.h, boxW, boxH, peek, rest: peek === 1 });
      const w = Math.max(1, Math.round(boxW * dpr));
      const h = Math.max(1, Math.round(boxH * dpr));
      if (target.width !== w) target.width = w;
      if (target.height !== h) target.height = h;
      paintTile(target, term, theme, { cell, scale: crop.scale, dpr, face, fontSize: FONT_SIZE, view: crop });
    };
    const pinnedTheme = untrack(() => row.pinned_theme ?? null);
    let unbindTheme: () => void = () => {};
    if (el) unbindTheme = bindTerminalTheme({ term: { options } }, el, { pinnedTheme });
    const unsubscribe = snapshotStore.subscribe(id, (shot) => {
      gone = shot.status === 'gone';
      unsupportedId = shot.status === 'unsupported' ? id : null;
      olderId = shot.status === 'older' ? id : null;
      if (shot.status !== 'ok') return;
      if (term.cols !== shot.cols || term.rows !== shot.rows) term.resize(shot.cols, shot.rows);
      paneWidth = shot.cols * cell.w;
      paneHeight = shot.rows * cell.h;
      term.reset();
      term.write(shot.screen, repaint);
    });
    return () => {
      unsubscribe();
      unbindTheme();
      repaint = () => {};
      term.dispose();
      paneWidth = 0;
      paneHeight = 0;
      gone = false;
    };
  });

  $effect(() => {
    const node = el;
    const Observer = (globalThis as { MutationObserver?: typeof MutationObserver }).MutationObserver;
    if (!node || typeof Observer !== 'function') return;
    const watcher = new Observer(() => repaint());
    watcher.observe(node, { attributes: true, attributeFilter: ['style', 'data-wr-zoomed'] });
    return () => watcher.disconnect();
  });

  $effect(() => {
    const id = socketId;
    if (!hovered || offline || !id) return;
    snapshotStore.setHot(id);
    return () => snapshotStore.releaseHot(id);
  });

  $effect(() => {
    void hovered;
    void paneWidth;
    void paneHeight;
    void bodyWidth;
    void bodyHeight;
    repaint();
  });

  function onkeydown(event: KeyboardEvent): void {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    onopen(row);
  }
</script>

{#if offline}
  <WarroomCard kind="offline" name={tile.name} lines={[offline, t('warroom.tile.offline')]} dim onopen={() => onopen(row)} />
{:else if older}
  <WarroomCard kind="remote" name={tile.name} lines={[t('warroom.tile.peer_update')]} onopen={() => onopen(row)} />
{:else if unsupported}
  <WarroomCard kind="remote" name={tile.name} lines={[t('warroom.tile.no_screen')]} onopen={() => onopen(row)} />
{:else}
  <div
    class="ww-tile"
    data-wr-tile={tile.key}
    data-wr-state={visible ? 'attached' : 'detached'}
    role="button"
    tabindex="0"
    aria-label={tile.name}
    bind:this={el}
    data-theme-scope
    onclick={() => onopen(row)}
    {onkeydown}
    onmouseenter={() => (hovered = true)}
    onmouseleave={() => (hovered = false)}
    onfocus={() => (hovered = true)}
    onblur={() => (hovered = false)}
  >
    <div class="ww-bar">
      <SessionFace {row} size="9px" />
      <span class="ww-name" use:truncatedTip={tile.name}>{tile.name}</span>
    </div>
    <div class="ww-body" bind:this={bodyEl}>
      <canvas
        class="ww-canvas"
        bind:this={canvas}
        style:width={`${bodyWidth}px`}
        style:height={`${bodyHeight}px`}
        style:visibility={paneWidth > 0 ? 'visible' : 'hidden'}
      ></canvas>
      {#if gone}<span class="ww-gone">{t('warroom.tile.gone')}</span>{/if}
    </div>
  </div>
{/if}
