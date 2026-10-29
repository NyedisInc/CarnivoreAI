<script lang="ts">
  /* the widget harness page */
  import { getContext, onDestroy, untrack } from 'svelte';
  import { t } from '../sdk';
  import type { FrameReport, LabSize } from '../sdk/widget-lab';
  import { frameHeight, frameUrl, frameWindowWidth, SIDEBAR_WINDOW, STAGE_PADDING_PX, type FrameSpec } from './frame-url';
  import { KEY_MENU_MESSAGE, MENU_CHOOSE, MENU_CLOSE, MENU_HIDE, MENU_SHOW, readMenuMessage } from '../sdk/widget-lab';
  import type { MenuHideMessage, MenuShowMessage, WireNode } from '../sdk/widget-lab';
  import type { MenuNode } from '../sdk';
  import PointerMenu from './PointerMenu.svelte';
  import { KEY_MENU_CONTEXT, toFramePoint, type KeyMenuBridge } from './key-menu-bridge';
  import { provideScenario, readReport, stageBottom, waitForReport, type HarnessWindow } from './frame-reader';

  interface Props {
    spec: FrameSpec;
    size: LabSize;
    scenario: string | null;
    title: string;
    onreport: (report: FrameReport | null) => void;
    onbox?: (box: { w: number; h: number }) => void;
    redraw?: boolean;
  }

  const { spec, size, scenario, title, onreport, onbox, redraw = false }: Props = $props();

  let frame = $state<HTMLIFrameElement | null>(null);
  let phase = $state<'loading' | 'drawn' | 'failed'>('loading');
  let measured = $state<number | null>(null);
  let gone = false;

  const EMPTY_BOX_PX = 96;

  const sidebar = $derived(spec.shell === 'sidebar');
  let clip = $state<{ w: number; h: number } | null>(null);
  let stepping = $state(false);
  const veiled = $derived(sidebar && (phase === 'loading' || stepping));
  const width = $derived(sidebar ? SIDEBAR_WINDOW.w : frameWindowWidth(size));
  const height = $derived(sidebar ? SIDEBAR_WINDOW.h : Math.max(frameHeight(size), (measured ?? 0) + STAGE_PADDING_PX));
  const contentHeight = $derived(sidebar ? (clip?.h ?? SIDEBAR_WINDOW.h) : spec.box ? size.h ?? EMPTY_BOX_PX : Math.max(size.h ?? 0, measured === null ? 0 : measured - 2 * STAGE_PADDING_PX, size.h === null && measured === null ? EMPTY_BOX_PX : 0));
  const box = $derived({ w: sidebar ? (clip?.w ?? size.w) : size.w, h: contentHeight, inset: sidebar ? 0 : STAGE_PADDING_PX });

  $effect(() => {
    onbox?.({ w: box.w, h: box.h });
  });

  const firstSrc = untrack(() => frameUrl(spec));
  const src = $derived(redraw ? firstSrc : frameUrl(spec));
  let drawnSize = untrack(() => `${spec.size}|${JSON.stringify(spec.view ?? null)}`);

  $effect(() => {
    const next = `${spec.size}|${JSON.stringify(spec.view ?? null)}`;
    if (!redraw || next === drawnSize || phase === 'loading') return;
    drawnSize = next;
    const win = frame?.contentWindow as (Window & HarnessWindow) | null | undefined;
    const show = win?.__widgetHarness?.show;
    if (!win || !show) return;
    stepping = true;
    void (async () => {
      try {
        await show({ zone: spec.host, size: spec.size, theme: spec.theme, ...(spec.view ? { view: spec.view } : {}) });
        if (gone) return;
        measured = stageBottom(win);
        const report = readReport(win);
        clip = report?.result?.clip ?? null;
        onreport(report);
      } finally {
        stepping = false;
      }
    })();
  });

  const keyMenu = getContext<KeyMenuBridge | undefined>(KEY_MENU_CONTEXT);
  const stopKeyMenu = keyMenu?.subscribe((key) => {
    const win = frame?.contentWindow;
    if (!win || !frame) return;
    pendingKey = { rect: key as DOMRect, at: performance.now() };
    const rect = frame.getBoundingClientRect();
    win.postMessage({ type: KEY_MENU_MESSAGE, ...toFramePoint(key, rect, frame.offsetWidth > 0 ? rect.width / frame.offsetWidth : 1) }, location.origin);
  });

  onDestroy(() => {
    gone = true;
    stopKeyMenu?.();
  });

  let remote = $state<{ id: number; label: string; at: { x: number; y: number }; size: { w: number; h: number }; nodes: MenuNode[] } | null>(null);
  let pendingKey: { rect: DOMRect; at: number } | null = null;
  const KEY_CLAIM_MS = 1500;

  function toFrame(message: object): void {
    frame?.contentWindow?.postMessage(message, location.origin);
  }

  function fromWire(id: number, nodes: readonly WireNode[], path: readonly string[] = []): MenuNode[] {
    return nodes.map((node) => {
      const here = [...path, node.id];
      const { runs, children, ...plain } = node;
      return { ...plain, ...(children ? { children: fromWire(id, children, here) } : {}), ...(runs ? { run: () => toFrame({ type: MENU_CHOOSE, id, path: here }) } : {}) };
    });
  }

  function onMessage(event: MessageEvent): void {
    if (!frame || event.source !== frame.contentWindow || event.origin !== location.origin) return;
    const shown = readMenuMessage<MenuShowMessage>(event.data, MENU_SHOW);
    if (shown) {
      const rect = frame.getBoundingClientRect();
      const scale = frame.offsetWidth > 0 ? rect.width / frame.offsetWidth : 1;
      const key = pendingKey && remote?.id !== shown.id && performance.now() - pendingKey.at < KEY_CLAIM_MS ? pendingKey.rect : null;
      pendingKey = null;
      const a = shown.anchor;
      const box = key ?? (a ? { left: rect.left + a.left * scale, top: rect.top + a.top * scale, width: (a.right - a.left) * scale, height: (a.bottom - a.top) * scale } : { left: rect.left, top: rect.top, width: 0, height: 0 });
      remote = { id: shown.id, label: shown.label, at: { x: box.left, y: box.top }, size: { w: box.width, h: box.height }, nodes: fromWire(shown.id, shown.nodes) };
      return;
    }
    const hidden = readMenuMessage<MenuHideMessage>(event.data, MENU_HIDE);
    if (hidden && remote?.id === hidden.id) remote = null;
  }

  function closeRemote(): void {
    if (!remote) return;
    toFrame({ type: MENU_CLOSE, id: remote.id });
    remote = null;
  }

  async function loaded(): Promise<void> {
    const win = frame?.contentWindow as (Window & HarnessWindow) | null | undefined;
    if (!win) return;
    provideScenario(win, scenario);
    const report = await waitForReport(win, () => gone);
    if (gone) return;
    measured = stageBottom(win);
    clip = report?.result?.clip ?? null;
    phase = report && !report.error ? 'drawn' : 'failed';
    onreport(report);
  }
</script>

<svelte:window onmessage={onMessage} />

<div class="dwl-frame-wrap" data-phase={phase} data-box={`${box.w}x${box.h}`} style:width={`${box.w}px`} style:height={`${box.h}px`}>
  <iframe
    bind:this={frame}
    class="dwl-frame"
    {title}
    {src}
    width={width}
    {height}
    style:margin={`-${box.inset}px`}
    style:visibility={veiled ? 'hidden' : undefined}
    data-veiled={veiled ? 'yes' : undefined}
    onload={() => void loaded()}
  ></iframe>
  {#if phase === 'loading'}<p class="dwl-note">{t('cplug.devwidgetlab.frame.loading')}</p>{/if}
</div>
{#if remote}
  {#key remote.id}<PointerMenu at={remote.at} size={remote.size} label={remote.label} nodes={remote.nodes} onclose={closeRemote} />{/key}
{/if}
