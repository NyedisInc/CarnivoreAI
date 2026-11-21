<script lang="ts">
  /* the history bar */
  import { t } from '../sdk';
  import { Button, Card, IconButton, List, ListRow, Markdown } from '../sdk/ui';
  import type { BoardRound, BoardSidecar } from './board-model';
  import { answerWords } from './tray-model';

  interface Props {
    sidecar: BoardSidecar;
    round: BoardRound;
    busy: boolean;
    onclose: () => void;
    onresend: () => void;
    onrelink: () => void;
  }

  let { sidecar, round, busy, onclose, onresend, onrelink }: Props = $props();

  const revision = $derived(sidecar.revisions.find((r) => r.id === round.revision));
  const answered = $derived(sidecar.revisions.find((r) => r.answers_round === round.id) ?? null);
  const diffKinds = ['added', 'removed', 'changed'] as const;
  const labelOf = (id: string): string => revision?.prompts.find((p) => p.id === id)?.label ?? id;
  const anchorLabel = (id: string): string => revision?.anchors.find((a) => a.id === id)?.label ?? id;
</script>

<Card title={t('cplug.reviewboard.round.title', { id: round.id, revision: round.revision })} compact data-round-card={round.id} data-delivery={round.delivery.state}>
  {#snippet actions()}
    <IconButton label={t('cplug.reviewboard.action.close')} icon="close" variant="close" iconSize={14} data-round-close onclick={onclose} />
  {/snippet}

  {#if round.delivery.state === 'undelivered'}
    <p class="rb-warn" role="status" data-round-undelivered>{t('cplug.reviewboard.round.undelivered', { reason: round.delivery.reason ?? '' })}</p>
    <div class="rb-actions">
      <Button variant="confirm" disabled={busy} data-round-resend onclick={onresend}>{t('cplug.reviewboard.round.resend')}</Button>
      <Button data-round-relink onclick={onrelink}>{t('cplug.reviewboard.round.relink')}</Button>
    </div>
  {:else if round.delivery.state === 'pending'}
    <p class="rb-note-text" role="status">{t('cplug.reviewboard.round.pending')}</p>
  {/if}

  {#if round.payload}
    <div class="rb-sent" data-round-payload>
      <p class="rb-note-text"><span class="rb-label">{t('cplug.reviewboard.round.payload_save', { n: round.save ?? 0 })}</span>
        {round.diff?.previous ? t('cplug.reviewboard.round.since', { id: round.diff.previous }) : t('cplug.reviewboard.round.first_send')}</p>
      {#each diffKinds as kind (kind)}
        {@const paths = round.diff?.[kind]}
        {#if paths && paths.length > 0}<p class="rb-note-text" data-round-diff={kind}><span class="rb-label">{t(`cplug.reviewboard.round.${kind}`)}</span> {paths.join(', ')}</p>{/if}
      {/each}
      {#if round.diff && round.diff.more > 0}<p class="rb-note-text">{t('cplug.reviewboard.round.more_paths', { count: round.diff.more })}</p>{/if}
    </div>
  {/if}
  <List density="dense">
    {#each round.answers as a (a.prompt)}
      <ListRow wrap>
        {#snippet primary()}<span class="rb-label">{labelOf(a.prompt)}</span> {answerWords(revision?.prompts.find((p) => p.id === a.prompt), a, t('cplug.reviewboard.tray.yes'), t('cplug.reviewboard.tray.no'))}
          {#if a.note}<em class="rb-sent-note">{a.note}</em>{/if}{/snippet}
      </ListRow>
    {/each}
    {#each round.anchor_notes as n (n.anchor)}
      <ListRow wrap>{#snippet primary()}<span class="rb-label">{anchorLabel(n.anchor)}</span> {n.text}{/snippet}</ListRow>
    {/each}
    {#if round.note}<ListRow wrap>{#snippet primary()}<span class="rb-label">{t('cplug.reviewboard.tray.note')}</span> {round.note}{/snippet}</ListRow>{/if}
  </List>
  {#if round.unanswered.length > 0}
    <p class="rb-note-text">{t('cplug.reviewboard.round.skipped', { prompts: round.unanswered.map(labelOf).join(', ') })}</p>
  {/if}
  {#if answered}
    <p class="rb-note-text" data-round-answered><span class="rb-label">{t('cplug.reviewboard.round.answered_by', { id: answered.id })}</span> <Markdown text={answered.summary} inline /></p>
  {/if}
</Card>
