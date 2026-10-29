<script lang="ts">
  import { t } from '../sdk';
  import { Button, Field, Icon, IconButton, List, ListRow, Markdown } from '../sdk/ui';
  import type { BoardRevision, BoardSidecar } from './board-model';
  import PromptRow from './PromptRow.svelte';
  import { confirmKey, type Confirm } from './round-confirm';
  import {
    anchorNoteOf, answerOf, copyGhost, ghostFor, isDraftEmpty, newDraft, pickOption, setAnchorNote, setChecked, setNote, setPromptNote, setText, shownRevision,
    draftCounts, type Draft,
  } from './tray-model';

  interface Props {
    sidecar: BoardSidecar;
    revision: BoardRevision;
    latest: BoardRevision;
    draft: Draft | null;
    phase: string;
    pointed: string | null;
    confirm: Confirm | null;
    sending: boolean;
    failed: boolean;
    hide?: string[];
    onedit: (change: (draft: Draft | null) => Draft | null) => void;
    onsend: () => void;
    onclear: () => void;
    onmove: () => void;
    onround: (id: string) => void;
  }

  let { sidecar, revision, latest, draft, phase, pointed, confirm, sending, failed, hide = [], onedit, onsend, onclear, onmove, onround }: Props = $props();

  let openAnchors = $state<string[]>([]);

  const editable = $derived(revision.id === latest.id);
  const draftRevision = $derived(sidecar.revisions.find((r) => r.id === draft?.revision) ?? latest);
  const stale = $derived(!!draft && !isDraftEmpty(draft) && draft.revision !== latest.id);
  const shown = $derived(shownRevision(sidecar, latest, draft));
  const counts = $derived(draftCounts(shown, draft));
  const left = $derived(counts.left);
  const canSend = $derived(!sending && !isDraftEmpty(draft));
  const roundsHere = $derived(sidecar.rounds.filter((r) => r.revision === revision.id));
  const answersRound = $derived(latest.answers_round);
  const anchorIds = $derived(shown.anchors.filter((a) => openAnchors.includes(a.id) || anchorNoteOf(draft, a.id) !== '' || a.id === pointed).map((a) => a.id));

  $effect(() => {
    if (pointed && !openAnchors.includes(pointed)) openAnchors = [...openAnchors, pointed];
  });

  $effect(() => {
    if (confirm) openAnchors = [];
  });

  function clearAll(): void {
    openAnchors = [];
    onclear();
  }

  function edit(change: (d: Draft) => Draft): void {
    onedit((d) => change(d ?? newDraft(latest.id)));
  }
</script>

<section class="rb-fold" data-tray aria-label={t('cplug.reviewboard.tray.label')}>
  <div class="rb-fold-body">
    <p class="rb-label" data-tray-caption>{editable ? t('cplug.reviewboard.tray.handle', { answered: counts.answered, left, noted: counts.noted }) : t('cplug.reviewboard.tray.older', { id: revision.id })}</p>
    {#if confirm}
      <p class="rb-confirm" data-confirm data-delivered={confirm.delivered} data-kept={confirm.kept ? 'true' : undefined} role="status">
        {t(confirmKey(confirm), { title: confirm.title, item: confirm.item })}
      </p>
    {/if}
    {#if failed}<p class="rb-warn" role="status" data-send-failed>{t('cplug.reviewboard.tray.send_failed')}</p>{/if}

    {#if !editable}
      <p class="rb-label">{t('cplug.reviewboard.tray.rounds_here', { id: revision.id })}</p>
      {#if roundsHere.length === 0}<p class="rb-note-text">{t('cplug.reviewboard.tray.none_sent')}</p>{/if}
      <List>
        {#each roundsHere as round (round.id)}
          <ListRow>
            <Button variant="row" data-tray-round={round.id} onclick={() => onround(round.id)}>
              <span class="rb-row-line">
                <span class="rb-row-title">{t('cplug.reviewboard.round.title', { id: round.id, revision: round.revision })}</span>
                <span class="rb-row-meta">{round.sent_at}</span>
              </span>
            </Button>
          </ListRow>
        {/each}
      </List>
    {:else}
      {#if phase === 'with_claude' && isDraftEmpty(draft)}
        <p class="rb-note-text" data-waiting>{t('cplug.reviewboard.tray.waiting', { id: `r${latest.n + 1}` })}</p>
      {/if}
      {#if answersRound}
        <div class="rb-changed" data-changed>
          <p class="rb-label">{t('cplug.reviewboard.tray.changed', { id: latest.id })}</p>
          <div class="rb-note-text" data-changed-summary><Markdown text={latest.summary} /></div>
          <Button variant="quiet" size="sm" data-answers-round onclick={() => onround(answersRound)}>{t('cplug.reviewboard.tray.answers_round', { id: answersRound })}</Button>
        </div>
      {/if}
      {#if stale}
        <div class="rb-notice" data-moved-notice role="status">
          <p>{t('cplug.reviewboard.tray.landed', { latest: latest.id, mine: draftRevision.id })}</p>
          <Button data-move-notes onclick={onmove}>{t('cplug.reviewboard.tray.move', { id: latest.id })}</Button>
        </div>
      {/if}

      {#each shown.prompts.filter((p) => !hide.includes(p.id)) as prompt (prompt.id)}
        {@const ghost = ghostFor(sidecar, prompt, shown.n)}
        <PromptRow {prompt} answer={answerOf(draft, prompt.id)} {ghost} highlighted={!!prompt.anchor && prompt.anchor === pointed}
                   onpick={(o) => edit((d) => pickOption(d, prompt, o))} oncheck={(c) => edit((d) => setChecked(d, prompt, c))}
                   ontext={(x) => edit((d) => setText(d, prompt, x))} onnote={(x) => edit((d) => setPromptNote(d, prompt, x))}
                   oncopy={() => ghost && edit((d) => copyGhost(d, prompt, ghost))} />
      {/each}

      {#if shown.anchors.length > 0}
        <div class="rb-anchors" data-anchors>
          <p class="rb-label">{t('cplug.reviewboard.tray.pin')}</p>
          <div class="rb-pills">
            {#each shown.anchors as anchor (anchor.id)}
              <Button size="sm" aria-pressed={anchorIds.includes(anchor.id)} data-anchor-pin={anchor.id}
                      onclick={() => (openAnchors = openAnchors.includes(anchor.id) ? openAnchors.filter((x) => x !== anchor.id) : [...openAnchors, anchor.id])}>{anchor.label}</Button>
            {/each}
          </div>
          {#each shown.anchors.filter((a) => anchorIds.includes(a.id)) as anchor (anchor.id)}
            <Field multiline block rows={2} aria-label={t('cplug.reviewboard.tray.note_for', { anchor: anchor.label })} data-anchor-note={anchor.id}
                   placeholder={t('cplug.reviewboard.tray.note_for', { anchor: anchor.label })} value={anchorNoteOf(draft, anchor.id)}
                   oninput={(e) => edit((d) => setAnchorNote(d, anchor.id, (e.currentTarget as HTMLInputElement).value))} />
          {/each}
        </div>
      {/if}

      <Field multiline block rows={3} aria-label={t('cplug.reviewboard.tray.note')} placeholder={t('cplug.reviewboard.tray.note_placeholder')}
             data-general-note value={draft?.note ?? ''} oninput={(e) => edit((d) => setNote(d, (e.currentTarget as HTMLInputElement).value))} />
    {/if}
  </div>

  {#if editable}
    <footer class="rb-fold-foot">
      <IconButton label={t('cplug.reviewboard.tray.clear')} icon="trash" variant="danger" iconSize={16} disabled={!draft} data-tray-clear onclick={clearAll} />
      <span class="rb-count" data-unanswered>{t('cplug.reviewboard.tray.unanswered', { left })}</span>
      <Button variant="confirm" size="icon" aria-label={t('cplug.reviewboard.tray.send')} title={t('cplug.reviewboard.tray.send')}
              disabled={!canSend} data-tray-send onclick={onsend}><Icon name="send" size={16} /></Button>
    </footer>
  {/if}
</section>
