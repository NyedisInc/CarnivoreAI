<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { t } from '../sdk';
  import type { FrameReport, LabWidget } from '../sdk/widget-lab';
  import { draftApi } from './lab-api';
  import { DraftStore } from './drafts-store.svelte';
  import { buildFailure, codeGap, compareDelta, draftWidget, findingCount, renewDelayMs, reportKey } from './drafts-model';
  import { drawnWidth, sizesOnShow } from './dock-box';
  import { bandSize, type LabSelection } from './lab-selection';
  import ComparePair from './ComparePair.svelte';

  interface Props {
    sel: LabSelection;
    widgets: readonly LabWidget[];
    scale: (frameWidth: number) => number;
    refreshSeq?: number;
  }

  const { sel, widgets, scale, refreshSeq = 0 }: Props = $props();

  const store = new DraftStore();
  let page = $state('');
  let ticketFor = '';
  let counts = $state<Record<string, number>>({});

  const draft = $derived(store.find(sel.draft));
  const widget = $derived(draft ? draftWidget(draft, widgets) : undefined);
  const hasCurrent = $derived(draft?.kind === 'revision' && sel.compare === 'side');
  const supported = $derived((widget?.hosts ?? []).filter((host) => host.supported));
  const bands = $derived.by(() => {
    const picked = supported.filter((host) => sel.hosts.includes(host.zone));
    return picked.length > 0 ? picked : supported;
  });
  const drawnBands = $derived(bands.flatMap((host) => (host.zone === 'drawer' ? sel.docks.map((dock) => ({ host, dock })) : [{ host, dock: sel.docks[0]! }])));
  const pairs = $derived(drawnBands.reduce((all, { host, dock }) => all + sizesOnShow(host, [bandSize(host, sel)?.name ?? ''], dock).length, 0));
  const delta = $derived(compareDelta(counts, pairs, hasCurrent));
  const built = $derived(draft?.build.state === 'built' && page !== '');
  const failure = $derived(draft ? buildFailure(draft) : '');
  const gap = $derived(draft ? codeGap(draft.code) : null);

  onMount(() => void store.refresh());

  let seenSeq = refreshSeq;
  $effect(() => {
    if (refreshSeq === seenSeq) return;
    seenSeq = refreshSeq;
    void store.refresh();
  });
  onDestroy(() => store.destroy());

  let renewTimer: ReturnType<typeof setTimeout> | null = null;
  onDestroy(() => {
    if (renewTimer !== null) clearTimeout(renewTimer);
  });

  function requestLink(slug: string): void {
    if (renewTimer !== null) clearTimeout(renewTimer);
    renewTimer = null;
    draftApi.ticket(slug).then(
      (link) => {
        page = link.path;
        renewTimer = setTimeout(() => requestLink(slug), renewDelayMs(link.expires_in));
        if (link.rebuild) void store.refresh();
      },
      (error: unknown) => console.warn('[widget lab] draft link', error),
    );
  }

  $effect(() => {
    const slug = draft?.slug;
    const stamp = draft?.build.state === 'built' ? `${slug}|${draft.build.built_at}` : '';
    if (!slug || !stamp || ticketFor === stamp) return;
    ticketFor = stamp;
    counts = {};
    requestLink(slug);
  });

  function reported(host: string, dock: string, size: string, side: 'current' | 'draft', report: FrameReport | null): void {
    counts = { ...counts, [reportKey(host, dock, size, side)]: findingCount(report) };
  }
</script>

<div class="dwl-compare" data-draft={sel.draft ?? ''}>
  {#if !draft}
    <p class="dwl-note dwl-note--error">{store.state.available ? t('cplug.devwidgetlab.compare.gone') : t('cplug.devwidgetlab.drafts.no_checkout')}</p>
  {:else}
    <p class="dwl-compare-strip" data-delta={delta.kind}>
      {#if !built}
        {draft.state === 'building' ? t('cplug.devwidgetlab.compare.building') : failure ? t('cplug.devwidgetlab.compare.failed') : t('cplug.devwidgetlab.compare.not_built')}
      {:else if delta.kind === 'new'}{draft.kind === 'new' ? t('cplug.devwidgetlab.compare.delta_new') : t('cplug.devwidgetlab.compare.draft_only')}
      {:else if delta.kind === 'waiting'}{t('cplug.devwidgetlab.compare.delta_waiting')}
      {:else}{t(`cplug.devwidgetlab.compare.delta_${delta.kind}`, { current: delta.current, draft: delta.draft })}{/if}
    </p>
    {#if gap}<p class="dwl-note" data-code-gap>{t('cplug.devwidgetlab.compare.code_gap', gap)}</p>{/if}
    {#if failure}<p class="dwl-note dwl-note--error">{failure}{#if draft.build.log} <span class="dwl-path">{draft.build.log}</span>{/if}</p>{/if}
    {#if draft.kind === 'revision' && !widget}<p class="dwl-note dwl-note--error">{t('cplug.devwidgetlab.compare.no_target', { widget: draft.widget })}</p>{/if}

    {#if built && widget}
      {#each drawnBands as { host, dock } (`${host.zone}:${host.zone === 'drawer' ? dock : ''}`)}
        <section class="dwl-host" data-host={host.zone} data-dock={host.zone === 'drawer' ? dock : undefined}>
          <header class="dwl-host-head"><span class="dwl-host-name">{host.zone === 'drawer' ? t(`cplug.devwidgetlab.dock.${dock}`) : t(`cplug.devwidgetlab.host.${host.zone}`)}</span></header>
          <div class="dwl-previews">
            {#each sizesOnShow(host, [bandSize(host, sel)?.name ?? ''], dock) as size (size.name)}
              <ComparePair host={host.zone} {dock} {size} widget={widget.key} title={widget.title} icon={widget.icon} theme={sel.theme} fixture={sel.fixture} {page} showCurrent={hasCurrent} sidebar={sel.sidebar}
                scale={scale(drawnWidth(host.zone, dock, size))} onreport={reported} />
            {/each}
          </div>
        </section>
      {/each}
    {/if}
  {/if}
</div>
