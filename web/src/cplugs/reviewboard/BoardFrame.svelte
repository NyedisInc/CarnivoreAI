<script lang="ts">
  /* the page frame */
  import { onMount, untrack } from 'svelte';
  import { t } from '../sdk';
  import { mintTicket } from './board-api';
  import { createBridgeHost, type DropReason } from './bridge-host';
  import { fitScale, frameWidth, type BoardRevision, type FitMode } from './board-model';
  import { layerStrings } from './layer-strings';
  import type { Payload } from './payload-model';
  import type { GapLayout } from './bridge-host';
  import InlineLayer from './InlineLayer.svelte';
  import type { InlineProps } from './inline-picks-model';

  interface Props {
    slug: string;
    revision: BoardRevision;
    view: string;
    mode: FitMode;
    room: number;
    capped?: boolean;
    reflows?: boolean;
    reload: number;
    marks?: { answered: string[]; noted: string[] };
    onready: (info: { anchors: string[]; themeAware: boolean }) => void;
    onanchor: (id: string) => void;
    onpayload?: (payload: Payload) => void;
    ondropped?: (reason: DropReason) => void;
    inline?: InlineProps | null;
  }

  let { slug, revision, view, mode, room, capped = false, reflows = false, reload, marks = { answered: [], noted: [] }, onready, onanchor, onpayload, ondropped, inline = null }: Props = $props();

  let frame = $state<HTMLIFrameElement | null>(null);
  let src = $state<string | null>(null);
  let failed = $state(false);
  let generation = 0;
  let spots = $state<GapLayout>({});
  let asked: Record<string, number> | null = null;

  const scale = $derived(!reflows && mode === 'fit' ? fitScale(revision.viewport, room) : 1);

  const width = $derived(reflows ? (room > 0 ? room : revision.viewport) : frameWidth(revision.viewport, room, scale));

  const bridge = createBridgeHost({
    frame: () => frame,
    declared: () => revision.anchors.map((a) => a.id),
    handlers: {
      ready: (info) => {
        bridge.state(marks.answered, marks.noted);
        if (asked) bridge.gaps(asked);
        if (revision.layer) bridge.strings(layerStrings());
        onready(info);
      },
      anchor: (id) => {
        bridge.highlight(id);
        onanchor(id);
      },
      payload: (payload) => onpayload?.(payload),
      layout: (found) => (spots = found),
      dropped: (reason) => ondropped?.(reason),
    },
  });

  export function load(payload: Payload, save: number | null): void {
    bridge.load(payload, save);
  }

  /* the page frame */
  export function theme(id: string, vars: Record<string, string>): void {
    bridge.theme(id, vars);
  }

  function askRoom(rooms: Record<string, number>): void {
    asked = rooms;
    bridge.gaps(rooms);
  }

  $effect(() => {
    if (inline || !asked) return;
    untrack(() => {
      bridge.gaps({});
      asked = null;
      spots = {};
    });
  });

  $effect(() => {
    bridge.state(marks.answered, marks.noted);
  });

  const key = $derived(`${slug}|${revision.id}|${view}|${reload}|${revision.stamp ?? ''}`);
  const place = $derived(`${slug}|${revision.id}|${view}|${reload}`);
  let shown = '';
  $effect(() => {
    void key;
    untrack(() => {
      const mine = ++generation;
      failed = false;
      if (place !== shown) src = null;
      shown = place;
      void mintTicket(slug, revision.id, view).then(
        (ticket) => {
          if (mine === generation) src = ticket.url;
        },
        () => {
          if (mine === generation) failed = true;
        },
      );
    });
  });

  onMount(() => {
    const listener = (event: MessageEvent): void => void bridge.handle(event);
    window.addEventListener('message', listener);
    return () => window.removeEventListener('message', listener);
  });
</script>

<div class="rb-box" class:rb-box--capped={capped} style:--rb-w="{width}px" style:--rb-scale={scale}>
  {#if failed}
    <p class="rb-note rb-note--error" role="status">{t('cplug.reviewboard.frame.unavailable')}</p>
  {:else if src}
    <iframe
      class="rb-frame"
      bind:this={frame}
      sandbox="allow-scripts"
      referrerpolicy="no-referrer"
      {src}
      title={t('cplug.reviewboard.frame.title', { id: revision.id })}
      data-board-frame
    ></iframe>
    {#if inline}
      <InlineLayer sidecar={inline.sidecar} prompts={inline.prompts} {spots} scale={scale} draft={inline.draft} revisionId={inline.revisionId} revisionN={inline.revisionN}
                   onedit={inline.onedit} onrooms={askRoom} onplaced={inline.onplaced} />
    {/if}
  {/if}
</div>
