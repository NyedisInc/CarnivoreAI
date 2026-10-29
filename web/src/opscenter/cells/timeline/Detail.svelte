<script lang="ts">
  /* the widget menu */
  import Glyph from '../../../lib/Glyph.svelte';
  import { Button, Card, Checkbox, IconButton } from '../../../lib/base';
  import BookmarkPreviewList from '../../../lib/bookmarks/BookmarkPreviewList.svelte';
  import type { PreviewEntry } from '../../../lib/bookmarks/preview-state.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { kindWord, markTitle } from './format';
  import type { Mark, SessionTimeline } from './types';
  import KindGlyph from './KindGlyph.svelte';
  import type { Item, PointAction } from './plot-model';
  import { tx } from './strings';
  import { clock, convBegan, convFacts, convLine, sleepWords, stamp } from './words';

  interface Props {
    data: SessionTimeline;
    item: Item | null;
    pinned: boolean;
    offers: Readonly<Record<PointAction, boolean>>;
    armed: boolean;
    live: boolean;
    busy: boolean;
    notice: { text: string; error?: boolean } | null;
    peek: PreviewEntry | null;
    onPick: (key: string) => void;
    onAction: (id: PointAction) => void;
    onArm: (on: boolean) => void;
    onClose: () => void;
  }

  let { data, item, pinned, offers, armed, live, busy, notice, peek, onPick, onAction, onArm, onClose }: Props = $props();

  const current = $derived(data.bars.findIndex((b) => b.current));
  const subject = $derived<Item | null>(item ?? (current >= 0 ? { key: `conv:${data.bars[current]!.conversation_id}`, kind: 'conversation', bar: data.bars[current]!, index: current, x: 0 } : null));
  const mark = $derived<Mark | null>(subject?.kind === 'mark' ? subject.mark : null);
  const head = $derived(
    !subject ? '' : subject.kind === 'mark' ? kindWord(subject.mark) : subject.kind === 'cluster' ? tx('cluster.label', { count: subject.marks.length })
      : subject.kind === 'sleep' ? t('opscenter.cell.timeline.kind.sleep') : `${subject.index + 1}`,
  );
  const ACTIONS: readonly PointAction[] = ['branch', 'rewind', 'bookmark', 'copy', 'open'];
</script>

{#if subject}
  <Card title={subject.kind === 'conversation' ? tx('conv.head', { n: head }) : head}
    meta={mark ? stamp(mark.at) : subject.kind === 'conversation' ? stamp(subject.bar.started_at) : ''} compact
    data-timeline-detail="card" data-pinned={pinned || undefined} data-kind={mark?.kind ?? subject.kind} aria-live="polite">
    {#snippet lead()}{#if mark}<KindGlyph kind={mark.kind} />{:else if subject.kind === 'sleep'}<KindGlyph kind="sleep" />{/if}{/snippet}
    {#snippet actions()}
      {#if pinned}
        <IconButton label={t('bookmarks.close')} variant="close" data-detail-close onclick={onClose}><Glyph name="close" /></IconButton>
      {/if}
    {/snippet}
    {#snippet children()}
    {#if subject.kind === 'mark'}
      <p class="tlx-card__title">{markTitle(subject.mark)}</p>
      {#if subject.mark.snippet && subject.mark.kind !== 'bookmark'}<p class="tlx-card__sub">{subject.mark.snippet}</p>{/if}
      <p class="tlx-card__sub">{convLine(data.bars.find((b) => b.conversation_id === subject.mark.conversation_id) ?? data.bars[0]!, data.bars.findIndex((b) => b.conversation_id === subject.mark.conversation_id))}</p>
      {#if pinned && peek}<BookmarkPreviewList entry={peek} />{/if}
    {:else if subject.kind === 'cluster'}
      <p class="tlx-card__sub">{tx('cluster.title', { count: subject.marks.length, from: clock(subject.marks[0]!.at), to: clock(subject.marks[subject.marks.length - 1]!.at) })}</p>
      <ul class="tlx-card__members">
        {#each subject.marks as m (m.id)}
          <li><Button variant="row" data-member={m.id} onclick={() => onPick(`mark:${m.id}`)}>
            <KindGlyph kind={m.kind} /><span class="tlx-member__t">{markTitle(m)}</span><span class="tlx-member__w">{clock(m.at)}</span>
          </Button></li>
        {/each}
      </ul>
    {:else if subject.kind === 'conversation'}
      <p class="tlx-card__title">{convBegan(subject.bar, data)}</p>
      <ul class="tlx-card__facts">{#each convFacts(subject.bar, data) as fact (fact)}<li>{fact}</li>{/each}</ul>
    {:else}
      {@const words = sleepWords(subject.gap, data)}
      <p class="tlx-card__title">{words[0]}</p>
      <p class="tlx-card__sub">{words[1]}</p>
    {/if}
    {#if data.marks.length === 0}<p class="tlx-card__hint">{tx('none.marks')}</p>{:else if !item}<p class="tlx-card__hint">{tx('hint.idle')}</p>{/if}
    {#if pinned && ACTIONS.some((a) => offers[a])}
      <div class="tlx-card__actions" role="group" aria-label={t('opscenter.cell.timeline.menu')}>
        {#each ACTIONS.filter((a) => offers[a]) as a (a)}
          <Button size="sm" data-action={a} disabled={busy || (a === 'rewind' && (!armed || !live))}
            onclick={() => onAction(a)}>{tx(`action.${a}`)}</Button>
        {/each}
      </div>
      {#if offers.rewind}
        <Checkbox tone="danger" label={live ? t('bookmarks.arm') : t('bookmarks.arm_not_live')} checked={armed} disabled={!live || busy} data-arm
          onchange={(e) => onArm(e.currentTarget.checked)} />
      {/if}
    {/if}
    {#if notice}<p class="tlx-card__notice" class:tlx-card__notice--error={notice.error} role="status">{notice.text}</p>{/if}
    {/snippet}
  </Card>
{/if}

<style>
  @layer components {
    .tlx-card__title { margin: 0; color: var(--oc-text-primary); font-size: var(--oc-fs-body); overflow-wrap: anywhere; }
    .tlx-card__sub,
    .tlx-card__facts { margin: 0; color: var(--oc-text-secondary); font-size: var(--oc-fs-label); overflow-wrap: anywhere; }
    .tlx-card__facts { padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 0 var(--oc-space-3); }
    .tlx-card__hint { margin: 0; color: var(--oc-text-dim); font-size: var(--oc-fs-label); }

    .tlx-card__members { margin: 0; padding: 0; list-style: none; }

    .tlx-member__t { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .tlx-member__w { color: var(--oc-text-muted); font-size: var(--oc-fs-micro); }

    .tlx-card__actions { display: flex; flex-wrap: wrap; gap: var(--oc-space-1); }

    .tlx-card__notice { margin: 0; color: var(--oc-text-secondary); font-size: var(--oc-fs-label); }
    .tlx-card__notice--error { color: var(--oc-coral); }
  }
</style>
