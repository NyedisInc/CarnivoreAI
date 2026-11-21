<script lang="ts">
  import { onMount } from 'svelte';
  import type { AnswerBody, AnswerSet, BoardResult, DraftResult, NextResult, PagePayload, PostBody, PostResult } from './board-client';
  import { createAutosave, type Autosave, type SaveLight } from './autosave';
  import { createVisitorBridge, wearTheme } from './frame-bridge';
  import { fitScale } from './frame-fit';
  import { layerStrings } from './layer-strings';
  import { watchNewer, type WatchDocument } from './newer-watch';
  import { t } from './strings';
  import VisitorForm from './VisitorForm.svelte';
  import VisitorKeys from './VisitorKeys.svelte';
  import VisitorRevisions from './VisitorRevisions.svelte';

  interface Props {
    load: (revision?: string) => Promise<BoardResult>; send?: (route: 'comments', body: PostBody) => Promise<PostResult>;
    save?: (body: { revision: string } & AnswerSet) => Promise<DraftResult>; wait?: (revision: string) => Promise<NextResult>;
    now?: () => number; doc?: WatchDocument;
  }
  let { load, send, save, wait, now = Date.now, doc = document }: Props = $props();

  const REFRESH_AT = 0.8;
  const DEFAULT_FRAME_TTL_S = 300;

  let result = $state<BoardResult | null>(null);
  let viewId = $state<string | null>(null);
  let room = $state(0);
  let fetchedAt = 0;

  const board = $derived(result?.kind === 'board' ? result.board : null);
  const view = $derived(board ? (board.views.find((v) => v.id === viewId) ?? board.views[0]) : null);
  const viewport = $derived(board?.viewport ?? 0);
  const scale = $derived(fitScale(viewport, room));
  const frameWidth = $derived(scale < 1 ? viewport : Math.max(viewport, room));
  const writable = $derived(Boolean(send) && board?.access !== 'read');
  const savedAnswers = $derived(board?.draft && 'answers' in board.draft.body ? board.draft.body.answers : []);

  let frameEl = $state<HTMLIFrameElement | null>(null);
  let pagePayload = $state<PagePayload | null>(null);
  let light = $state<SaveLight>('idle');
  let newerRevision = $state<string | null>(null);
  let movedTo = $state<string | null>(null);
  let moveGeneration = 0;
  let reviewing = $state<string | null>(null);
  const newest = $derived(board?.revisions?.at(-1)?.revision ?? board?.revision ?? null);
  let autosave: Autosave | null = null;

  const bridge = createVisitorBridge(() => frameEl, {
    ready: () => {
      if (board?.layer && !writable) bridge.mode(true); // a read only link
      if (board?.theme) bridge.theme(board.theme);
      if (board?.layer) bridge.strings(layerStrings());
      const saved = pagePayload ?? (board?.draft && 'payload' in board.draft.body ? board.draft.body.payload : null);
      if (saved) bridge.load(saved);
    },
    payload: (payload) => {
      if (!writable) return;
      pagePayload = payload;
      autosave?.change({ payload });
    },
  }, () => now());

  $effect(() => {
    wearTheme(document.documentElement, board?.theme);
  });

  $effect(() => {
    const revision = board?.revision;
    if (!revision || !save || !writable) return;
    const own = createAutosave((answers) => save({ revision, ...answers }), (shown) => (light = shown));
    autosave = own;
    return () => {
      void own.flush().then(() => own.stop());
      if (autosave === own) autosave = null;
    };
  });

  // a newer revision
  $effect(() => {
    const revision = newest;
    if (!revision || !wait) return;
    return watchNewer(() => wait(revision), (next) => { void onNewer(next); }, doc);
  });

  function take(answer: BoardResult): void {
    result = answer;
    fetchedAt = now();
  }

  onMount(() => {
    void load().then(take);
    const onMessage = (event: MessageEvent): void => { bridge.handle(event); };
    const onHide = (): void => { if (doc.hidden) void autosave?.flush(); };
    const onLeave = (): void => { void autosave?.flush(); };
    window.addEventListener('message', onMessage);
    doc.addEventListener('visibilitychange', onHide);
    window.addEventListener('pagehide', onLeave);
    return () => {
      window.removeEventListener('message', onMessage);
      doc.removeEventListener('visibilitychange', onHide);
      window.removeEventListener('pagehide', onLeave);
    };
  });

  async function showRevision(revision?: string): Promise<boolean> {
    const mine = ++moveGeneration;
    await autosave?.flush();
    if (mine !== moveGeneration) return false;
    newerRevision = null;
    movedTo = null;
    pagePayload = null;
    viewId = null;
    const answer = await load(revision);
    if (mine !== moveGeneration) return false;
    reviewing = answer.kind === 'board' && answer.board.revision !== answer.board.revisions?.at(-1)?.revision && revision ? answer.board.revision : null;
    take(answer);
    return true;
  }

  async function moveToNewer(): Promise<void> {
    await showRevision();
  }

  async function onNewer(next: string): Promise<void> {
    if (reviewing) { newerRevision = next; return; }
    if (await showRevision()) movedTo = next;
  }

  function sendOnScreen(route: 'comments', body: PostBody): Promise<PostResult> {
    if (!send) return Promise.resolve({ kind: 'state', state: 'unavailable' });
    return send(route, board ? { ...body, revision: board.revision } : body);
  }

  function answersChanged(answers: AnswerBody[]): void {
    autosave?.change({ answers });
  }

  async function choose(id: string): Promise<void> {
    if (!board || id === view?.id) return;
    const lifetimeMs = (board.frame_ttl ?? DEFAULT_FRAME_TTL_S) * 1000;
    if (now() - fetchedAt >= lifetimeMs * REFRESH_AT) {
      const mine = moveGeneration;
      const fresh = await load(reviewing ?? undefined);
      if (mine !== moveGeneration) return;
      if (fresh.kind === 'board' || fresh.state === 'ended' || fresh.state === 'invalid') take(fresh);
      if (result?.kind !== 'board') return;
    }
    viewId = id;
  }

  function endsText(epoch: number): string {
    return t('cplug.reviewboard.public.page.expires', { when: new Date(epoch * 1000).toLocaleString() });
  }

  function measure(node: HTMLElement): { destroy: () => void } {
    room = node.clientWidth;
    const watcher = new ResizeObserver(() => {
      room = node.clientWidth;
    });
    watcher.observe(node);
    return { destroy: () => watcher.disconnect() };
  }
</script>

<main class="pb">
  <header class="pb-titlebar" data-visitor-bar>
    <span class="pb-label">{t(writable ? 'cplug.reviewboard.public.page.answering' : 'cplug.reviewboard.public.page.read_only')}</span>
    <h1 class="pb-title">{board ? board.title : t('cplug.reviewboard.public.page.title')}</h1>
    {#if board}
      {#if (board.revisions ?? []).length > 1}
        <VisitorRevisions revisions={board.revisions ?? []} shown={board.revision} pick={(revision) => void showRevision(revision === newest ? undefined : revision)} />
      {:else}
        <span class="pb-meta">{t('cplug.reviewboard.public.page.revision', { revision: board.revision })}</span>
      {/if}
      <span class="pb-bar-end">
        {#if writable && light !== 'idle'}
          <span class="pb-save" data-light={light} role="status" data-visitor-saved>{t(`cplug.reviewboard.public.page.save.${light}`)}</span>
        {/if}
        {#if movedTo}
          <button type="button" class="pb-newer" data-btn="quiet" data-size="sm" onclick={() => (movedTo = null)} data-visitor-moved
                  title={t('cplug.reviewboard.public.page.moved_hint')}>{t('cplug.reviewboard.public.page.moved', { revision: movedTo })}</button>
        {/if}
        {#if newerRevision}
          <button type="button" class="pb-newer" data-btn="quiet" data-size="sm" onclick={() => void moveToNewer()} data-visitor-newer
                  title={t('cplug.reviewboard.public.page.newer_hint', { revision: newerRevision })}>{t('cplug.reviewboard.public.page.newer', { revision: newerRevision })}</button>
        {/if}
        {#if send && writable}<VisitorKeys anchors={board.anchors ?? []} send={sendOnScreen} />{/if}
      </span>
    {/if}
  </header>

  {#if result === null}
    <p class="pb-note" role="status">{t('cplug.reviewboard.public.page.loading')}</p>
  {:else if result.kind === 'state'}
    <p class="pb-note pb-note--state" role="alert" data-state={result.state}>{t(`cplug.reviewboard.public.page.state.${result.state}`)}</p>
  {:else if board && view}
    {#if board.summary}
      <section class="pb-section">
        <h2 class="pb-label">{t('cplug.reviewboard.public.page.summary')}</h2>
        <p class="pb-summary">{board.summary}</p>
      </section>
    {/if}

    {#if board.views.length > 1}
      <section class="pb-section">
        
        <div class="oc-segmented" role="radiogroup" aria-label={t('cplug.reviewboard.public.page.views')}>
          {#each board.views as v (v.id)}
            <button type="button" data-btn="quiet" data-size="sm" role="radio" aria-checked={v.id === view.id} onclick={() => void choose(v.id)}>{v.label}</button>
          {/each}
        </div>
      </section>
    {/if}

    <section class="pb-stage">
      <div class="pb-fit" use:measure></div>
      <div class="pb-box" style:--pb-w="{frameWidth}px" style:--pb-scale={scale}>
        {#key view.frame}
          <iframe class="pb-frame" sandbox="allow-scripts" referrerpolicy="no-referrer" src={view.frame} title={t('cplug.reviewboard.public.page.frame', { label: view.label })}
                  bind:this={frameEl}></iframe>
        {/key}
      </div>
    </section>

    {#if send && writable}
      {#if (board.prompts ?? []).length === 0 && (board.layer || pagePayload)}
        <section class="pb-section pbf" data-visitor-page-saves>
          <p class="pb-hint">{t('cplug.reviewboard.public.page.page_answers')}</p>
        </section>
      {/if}
      {#key board.revision}
        <VisitorForm prompts={board.prompts ?? []} initial={savedAnswers} onchange={answersChanged} />
      {/key}
    {:else if board.prompts && board.prompts.length > 0}
      <section class="pb-section">
        <h2 class="pb-label">{t('cplug.reviewboard.public.page.prompts')}</h2>
        <p class="pb-hint">{t('cplug.reviewboard.public.page.prompts_note')}</p>
        <ol class="pb-prompts">
          {#each board.prompts as prompt (prompt.id)}
            <li>
              <span class="pb-prompt-label">{prompt.label}</span>
              {#if prompt.options.length > 0}
                <span class="pb-hint">{t('cplug.reviewboard.public.page.prompt_options', { options: prompt.options.map((o) => o.label).join(', ') })}</span>
              {/if}
            </li>
          {/each}
        </ol>
      </section>
    {/if}

    {#if board.expires_at}
      <footer class="pb-foot">{endsText(board.expires_at)}</footer>
    {/if}
  {/if}
</main>
