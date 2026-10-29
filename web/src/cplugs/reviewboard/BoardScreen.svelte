<script lang="ts">
  /* the history bar the notes panel the page frame */
  import { onMount, untrack } from 'svelte';
  import { activeThemeId, ApiError, markdownPlain, resourcePush, t } from '../sdk';
  import { Button, ConfirmPopup, IconButton, Segmented } from '../sdk/ui';
  import { clearScratch, fetchBoard, fetchBoards, rescan } from './board-api';
  import AttachmentsKey from './AttachmentsKey.svelte';
  import NotesPanel from './NotesPanel.svelte';
  import { NoteKeeper, noteKey } from './note-store';
  import BoardFrame from './BoardFrame.svelte';
  import BoardPicker from './BoardPicker.svelte';
  import HistoryBar from './HistoryBar.svelte';
  import RelinkPicker from './RelinkPicker.svelte';
  import PayloadControls from './PayloadControls.svelte';
  import PayloadNotices from './PayloadNotices.svelte';
  import { PayloadLoop } from './payload-loop.svelte';
  import { ReviewLoop } from './review-loop.svelte';
  import LiveBar from './LiveBar.svelte';
  import { inlinePrompts, type InlineProps } from './inline-picks-model';
  import { withLiveDraft } from './live-model';
  import RoundView from './RoundView.svelte';
  import ThemePicker from './ThemePicker.svelte';
  import Tray from './Tray.svelte';
  import { effectiveTheme, flatChoices, readThemeChoice, themeGroups, tokensFor, writeThemeChoice } from './board-theme';
  import { anchorState, newDraft, setNote, shownRevision, unansweredCount } from './tray-model';
  import {
    BOARDS_TOPIC, DRAFTS_TOPIC, cappedRoom, hasSetWidth, widthCap, MAIN_VIEW, defaultFit, historyItems, isScratch, latestRevision, paramsFromSearch, revisionById, stepRevision, visibleHistory,
    type BoardAnswer, type BoardListRow, type FitMode,
  } from './board-model';
  import { readFullWidth, writeFullWidth } from './board-width';
  import './board.css';
  import './tray.css';
  import './header.css';

  const POLL_MS = 30000;

  let slug = $state<string | null>(null);
  let pinned = $state<string | null>(null);
  let answer = $state<BoardAnswer | null>(null);
  let boards = $state<BoardListRow[]>([]);
  let errorKey = $state<string | null>(null);
  let loading = $state(true);
  let view = $state(MAIN_VIEW);
  let room = $state(0);
  let fullWidth = $state(readFullWidth());
  let promptsOpen = $state(false);
  let themeChoice = $state(readThemeChoice());
  let themeSet = $state(themeGroups());
  let appTheme = $state(activeThemeId());
  let reload = $state(0);
  let unfolded = $state(false);
  let pointed = $state<string | null>(null);
  let themeAware = $state<boolean | null>(null);
  let flipped = $state(false);
  let openRound = $state<string | null>(null);
  let relinking = $state(false);
  let clearing = $state(false);
  let clearKey = $state<HTMLElement | null>(null);
  let clearFailed = $state(false);
  let noteOpen = $state(false);
  let boardsTick = $state(0);
  let frameApi = $state<ReturnType<typeof BoardFrame> | null>(null);
  const loop = new ReviewLoop(() => load());
  const payloadLoop = new PayloadLoop(() => load(), (payload, save) => frameApi?.load(payload, save));

  /* the page frame */
  const frameTheme = $derived(effectiveTheme(themeChoice, flatChoices(themeSet), appTheme));

  function refreshThemes(): void {
    themeSet = themeGroups();
    appTheme = activeThemeId();
  }

  function paintTheme(): void {
    const id = frameTheme;
    const vars = id ? tokensFor(id) : null;
    if (id && vars) frameApi?.theme(id, vars);
  }

  function pickTheme(id: string): void {
    themeChoice = id;
    writeThemeChoice(id);
    paintTheme();
  }

  const sidecar = $derived(withLiveDraft(answer?.sidecar ?? null));
  const live = $derived(answer?.sidecar?.live ?? null);
  let placed = $state<string[]>([]);
  const latest = $derived(sidecar ? latestRevision(sidecar) : null);
  const revision = $derived(sidecar ? (revisionById(sidecar, pinned) ?? latest) : null);
  const onNewest = $derived(!!revision && !!latest && revision.id === latest.id);
  const shownView = $derived(revision?.views.some((v) => v.id === view) ? view : MAIN_VIEW);
  const previous = $derived(sidecar && revision ? (sidecar.revisions[revision.n - 2] ?? null) : null);
  const frameRevision = $derived(flipped && previous ? previous : revision);
  const layered = $derived(!!(frameRevision ?? revision)?.layer);
  const asksWidth = $derived(hasSetWidth(frameRevision ?? revision));
  const cap = $derived(widthCap(frameRevision ?? revision, fullWidth));
  const reflows = $derived(layered || cap !== null);
  const shownRoom = $derived(cappedRoom(room, cap));
  const mode = $derived<FitMode>(revision ? (reflows ? 'actual' : defaultFit(revision.viewport, shownRoom)) : 'actual');
  const history = $derived(sidecar ? visibleHistory(historyItems(sidecar), sidecar.revisions.length, unfolded) : null);
  const framed = typeof window !== 'undefined' && window.self !== window.top;
  const payloadRevision = $derived((frameRevision ?? revision)?.payload_mode ? (frameRevision ?? revision) : null);
  const marks = $derived(revision ? anchorState(revision, loop.draft) : { answered: [], noted: [] });
  const promptsLeft = $derived(sidecar && latest ? unansweredCount(shownRevision(sidecar, latest, loop.draft), loop.draft) : 0);
  const inlineList = $derived(inlinePrompts(frameRevision ?? revision, onNewest && !flipped && !payloadRevision));
  const inline = $derived<InlineProps | null>(
    sidecar && latest && inlineList.length > 0
      ? { sidecar, prompts: inlineList, draft: loop.draft, revisionId: latest.id, revisionN: latest.n, onedit: (change) => loop.edit(change), onplaced: (ids) => (placed = ids) }
      : null,
  );
  const roundShown = $derived(sidecar?.rounds.find((r) => r.id === openRound) ?? null);
  const pointedAnchor = $derived(revision?.anchors.find((a) => a.id === pointed) ?? null);
  const pointedPrompts = $derived(pointed ? (revision?.prompts.filter((p) => p.anchor === pointed) ?? []) : []);
  const noteKeeper = new NoteKeeper();
  const noteText = $derived(payloadRevision ? payloadLoop.note : (loop.draft?.note ?? ''));

  function setNoteText(text: string): void {
    if (payloadRevision) {
      payloadLoop.setNote(text);
      return;
    }
    const on = latest?.id;
    if (on) loop.edit((d) => setNote(d ?? newDraft(on), text));
  }

  async function sendPayload(): Promise<void> {
    if (!sidecar || !payloadRevision) return;
    noteOpen = false;
    await payloadLoop.send(sidecar, payloadRevision.id, viewContext());
  }

  $effect(() => {
    if (!sidecar || !payloadRevision) return;
    const slug = sidecar.board.slug;
    const id = payloadRevision.id;
    untrack(() => payloadLoop.attach(slug, id));
    const back = noteKeeper.follow(noteKey(slug, id), payloadLoop.note);
    if (back !== null) untrack(() => payloadLoop.setNote(back));
  });

  function errorKeyFor(error: unknown): string {
    if (error instanceof ApiError && error.status === 404) return 'cplug.reviewboard.page.not_found';
    if (error instanceof ApiError && error.status === 409 && error.code === 'reviewboard_no_root') return 'cplug.reviewboard.page.no_root';
    return 'cplug.reviewboard.page.failed';
  }

  async function load(): Promise<void> {
    try {
      if (slug) answer = await fetchBoard(slug);
      else boards = (await fetchBoards()).boards;
      errorKey = null;
    } catch (error) {
      errorKey = errorKeyFor(error);
    } finally {
      loading = false;
    }
  }

  function openBoard(next: string): void {
    slug = next;
    pinned = null;
    answer = null;
    noteOpen = false;
    loading = true;
    void loop.open(next);
    const url = new URL(window.location.href);
    url.searchParams.set('board', next);
    url.searchParams.delete('rev');
    window.history.replaceState(null, '', url);
    void load();
  }

  async function clearBoard(): Promise<void> {
    if (!slug) return;
    try {
      await clearScratch(slug);
    } catch {
      clearing = false;
      clearFailed = true;
      return;
    }
    clearing = false;
    loop.close();
    slug = null;
    answer = null;
    const url = new URL(window.location.href);
    url.searchParams.delete('board');
    url.searchParams.delete('rev');
    window.history.replaceState(null, '', url);
    await load();
  }

  function show(id: string): void {
    pinned = latest && id === latest.id ? null : id;
    view = MAIN_VIEW;
    pointed = null;
    themeAware = null;
    flipped = false;
    openRound = null;
  }

  function toggleWidth(): void {
    fullWidth = !fullWidth;
    writeFullWidth(fullWidth);
  }

  function step(delta: number): void {
    if (sidecar && revision) show(stepRevision(sidecar, revision.id, delta));
  }

  async function readAgain(): Promise<void> {
    try {
      await rescan();
      reload += 1;
      await load();
    } catch (error) {
      errorKey = errorKeyFor(error);
    }
  }

  function send(): void {
    if (!sidecar) return;
    void loop.send(sidecar, viewContext()).then(() => {
      if (loop.failed) return;
      pointed = null;
    });
  }

  function viewContext(): { width: number | null; fit: FitMode; view: string } {
    return { width: shownRoom > 0 ? Math.round(shownRoom) : null, fit: mode, view: shownView };
  }

  async function relinkTo(item: number): Promise<void> {
    relinking = false;
    await loop.relink(item);
  }

  function popOut(): void {
    window.open(window.location.href, '_blank', 'noopener');
  }

  onMount(() => {
    const params = paramsFromSearch(window.location.search);
    untrack(() => {
      slug = params.board;
      pinned = params.rev;
    });
    void load();
    if (params.board) void loop.open(params.board);
    const leaving = (): void => void payloadLoop.flush();
    const hiding = (): void => {
      if (document.visibilityState === 'hidden') leaving();
    };
    document.addEventListener('visibilitychange', hiding);
    window.addEventListener('pagehide', leaving);
    const stopBoards = resourcePush().pushOrPoll(() => {
      boardsTick += 1;
      void load();
    }, POLL_MS, [BOARDS_TOPIC]);
    const stopDrafts = resourcePush().pushOrPoll(() => void loop.remoteChanged(), POLL_MS, [DRAFTS_TOPIC]);
    return () => {
      document.removeEventListener('visibilitychange', hiding);
      window.removeEventListener('pagehide', leaving);
      leaving();
      stopBoards();
      stopDrafts();
      loop.close();
    };
  });
</script>

<div class="rb" data-board-page>
  {#if !slug}
    {#if loading}
      <p class="rb-note" role="status">{t('cplug.reviewboard.page.loading')}</p>
    {:else if errorKey}
      <p class="rb-note rb-note--error" role="status">{t(errorKey)}</p>
    {:else}
      <BoardPicker {boards} onpick={openBoard} />
    {/if}
  {:else}
    <div class="rb-strip" data-board-strip>
      <span class="rb-name">{sidecar?.board.title ?? slug}</span>
      {#if answer && answer.state !== 'your_turn'}<span class="rb-state" data-state={answer.state}>{t(`cplug.reviewboard.state.${answer.state}`)}</span>{/if}
      {#if revision}
        <ThemePicker groups={themeSet} value={themeChoice} active={appTheme} onchange={pickTheme} onrefresh={refreshThemes} />
      {/if}
      {#if payloadRevision}
        <PayloadControls revision={payloadRevision} loop={payloadLoop} {noteOpen} onnote={() => (noteOpen = !noteOpen)} onsend={() => void sendPayload()}
                         onstep={(delta) => payloadLoop.step(payloadRevision, delta)} />
      {:else if latest}
        <Button size="sm" aria-expanded={promptsOpen} title={t('cplug.reviewboard.fold.title')}
                data-prompts-key onclick={() => (promptsOpen = !promptsOpen)}>{t('cplug.reviewboard.fold.prompts')}{#if promptsLeft > 0}<span class="rb-fold-count" data-prompts-count>{promptsLeft}</span>{/if}</Button>
        <IconButton label={t('cplug.reviewboard.notes.key')} icon="chat" variant="quiet" iconSize={16} aria-expanded={noteOpen}
                    data-filled={noteText.trim() !== ''} data-board-note-key onclick={() => (noteOpen = !noteOpen)} />
      {/if}
      {#if sidecar && !isScratch(sidecar)}
        <AttachmentsKey slug={sidecar.board.slug} tick={boardsTick} />
      {/if}
      <span class="rb-tools">
        <IconButton label={t('cplug.reviewboard.action.back')} icon="chevron-left" variant="quiet" iconSize={16}
                    disabled={!revision || revision.n <= 1} onclick={() => step(-1)} />
        <IconButton label={t('cplug.reviewboard.action.forward')} icon="chevron-right" variant="quiet" iconSize={16}
                    disabled={!revision || onNewest} onclick={() => step(1)} />
        <IconButton label={t('cplug.reviewboard.action.flip')} icon="cycle" variant="quiet" iconSize={16}
                    disabled={!previous} pressed={flipped} data-board-flip onclick={() => (flipped = !flipped)} />
        <IconButton label={t('cplug.reviewboard.action.link')} icon="link" variant="quiet" iconSize={16}
                    disabled={!sidecar} data-board-link onclick={() => (relinking = !relinking)} />
        {#if asksWidth}
          <IconButton label={t(fullWidth ? 'cplug.reviewboard.action.width_max' : 'cplug.reviewboard.action.width_full')} icon={fullWidth ? 'shrink' : 'expand'}
                      variant="quiet" iconSize={16} pressed={fullWidth} data-board-width onclick={toggleWidth} />
        {/if}
        <IconButton label={t('cplug.reviewboard.action.rescan')} icon="reset" variant="quiet" iconSize={16} onclick={() => void readAgain()} />
        {#if isScratch(sidecar)}
          <IconButton label={t('cplug.reviewboard.scratch.clear_key')} icon="trash" variant="danger" iconSize={16}
                      pressed={clearing} data-board-clear bind:element={clearKey} onclick={() => { clearing = !clearing; clearFailed = false; }} />
        {/if}
        {#if framed}
          <IconButton label={t('cplug.reviewboard.action.popout')} icon="external" variant="quiet" iconSize={16} onclick={popOut} />
        {/if}
      </span>
    </div>

    {#if live && answer}<LiveBar slug={answer.slug} {live} onchanged={load} />{/if}

    {#if clearing}
      <ConfirmPopup label={t('cplug.reviewboard.scratch.clear_key')} message={t('cplug.reviewboard.scratch.clear_confirm')} anchor={clearKey}
                    cancelLabel={t('cplug.reviewboard.scratch.cancel')} confirmLabel={t('cplug.reviewboard.scratch.clear')}
                    data-board-clear-confirm confirmProps={{ 'data-board-clear-go': '' }}
                    onConfirm={() => void clearBoard()} onCancel={() => (clearing = false)} />
    {/if}
    {#if clearFailed}
      <p class="rb-note rb-note--error" role="status">{t('cplug.reviewboard.scratch.clear_failed')}</p>
    {/if}
    {#if loading && !answer}
      <p class="rb-note" role="status">{t('cplug.reviewboard.page.loading')}</p>
    {:else if errorKey && !answer}
      <p class="rb-note rb-note--error" role="status">{t(errorKey)}</p>
    {:else if answer && answer.status === 'newer'}
      <p class="rb-note" role="status">{t('cplug.reviewboard.page.newer')}</p>
    {:else if answer && !sidecar}
      <p class="rb-note rb-note--error" role="status">{t('cplug.reviewboard.page.invalid')}</p>
    {:else if sidecar && history && revision}
      <HistoryBar items={history.items} folded={history.folded} current={revision.id} total={sidecar.revisions.length}
                  onpick={show} onround={(id) => (openRound = id)} onunfold={() => (unfolded = true)} />
      {#if revision.views.length > 1 || !onNewest}
        <div class="rb-views">
          {#if revision.views.length > 1}
            <Segmented label={t('cplug.reviewboard.views.label')} value={shownView} options={revision.views.map((one) => ({ value: one.id, label: one.label }))}
                       onchange={(id) => (view = id)} />
          {/if}
          {#if !onNewest && latest}
            <span class="rb-back"><Button size="sm" data-back-current onclick={() => show(latest.id)}>{t('cplug.reviewboard.action.back_to_current')}</Button></span>
          {/if}
        </div>
      {/if}
      {#if payloadRevision}<PayloadNotices revision={payloadRevision} loop={payloadLoop} />{/if}
      <div class="rb-body" data-board-body>
        <div class="rb-main">
        {#if !payloadRevision && latest && promptsOpen}
          <Tray {sidecar} {revision} {latest} draft={loop.draft} phase={answer?.state ?? 'your_turn'} {pointed} confirm={loop.confirm}
                sending={loop.sending} failed={loop.failed} hide={inline ? placed : []} onedit={(change) => loop.edit(change)} onsend={send} onclear={() => { pointed = null; loop.clear(); }}
                onmove={() => latest && loop.move(sidecar.revisions.find((r) => r.id === loop.draft?.revision) ?? revision, latest)}
                onround={(id) => (openRound = id)} />
        {/if}
        <div class="rb-stage" bind:clientWidth={room} data-board-stage>
          <BoardFrame bind:this={frameApi} slug={sidecar.board.slug} revision={frameRevision ?? revision} view={shownView} {mode} room={shownRoom} capped={cap !== null} {reflows} {reload} {marks} {inline}
                      onready={(info) => { themeAware = info.themeAware; refreshThemes(); paintTheme(); if (payloadRevision) payloadLoop.pageReady(payloadRevision); }}
                      onanchor={(id) => { pointed = id; if (!payloadRevision) promptsOpen = true; }} onpayload={(payload) => payloadLoop.received(payload)}
                      ondropped={(reason) => { if (payloadRevision && (reason === 'payload' || reason === 'size')) payloadLoop.rejected(); }} />
        </div>
        <div class="rb-readout" data-board-readout>
          {#if pointedAnchor}
            <p data-board-pointed><span class="rb-label">{t('cplug.reviewboard.point.label')}</span> {pointedAnchor.label}{#if pointedPrompts.length > 0}: {pointedPrompts.map((p) => p.label).join(', ')}{/if}</p>
          {/if}
          {#if themeAware === false}<p class="rb-chip">{t('cplug.reviewboard.frame.ignores_theme')}</p>{/if}
          <p><span class="rb-label">{(frameRevision ?? revision).id}</span> <span data-board-summary>{markdownPlain((frameRevision ?? revision).summary)}</span></p>
        </div>
        </div>
        {#if noteOpen && (payloadRevision || latest)}
          <NotesPanel value={noteText} oninput={setNoteText} onclose={() => (noteOpen = false)}
                      placeholder={t(payloadRevision ? 'cplug.reviewboard.payload.note_placeholder' : 'cplug.reviewboard.tray.note_placeholder')}
                      panelProps={payloadRevision ? { 'data-payload-note-pop': '' } : {}} textProps={payloadRevision ? { 'data-payload-note': '' } : { 'data-board-note': '' }} />
        {/if}
        {#if roundShown || relinking}
          <div class="rb-over" data-board-over>
            {#if relinking}
              <RelinkPicker list={sidecar.task?.list ?? 'all'} current={sidecar.task?.item_id ?? null} onpick={(id) => void relinkTo(id)} onclose={() => (relinking = false)} />
            {:else if roundShown}
              <RoundView {sidecar} round={roundShown} busy={loop.busy} onclose={() => (openRound = null)} onresend={() => void loop.resend(roundShown.id)}
                         onrelink={() => (relinking = true)} />
            {/if}
          </div>
        {/if}
      </div>
    {:else if sidecar}
      <p class="rb-note">{t('cplug.reviewboard.page.empty')}</p>
    {/if}
  {/if}
</div>
