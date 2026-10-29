
<script lang="ts">
  import { t } from '../../../i18n/index.svelte';
  import { Character } from '../../../../cplugs/huddle/swarm/characters';
  import { activePack } from '../../../../cplugs/huddle/swarm/swarm-settings.svelte';
  import StatusGlyph from '../../StatusGlyph.svelte';
  import SentBackGlyph from './SentBackGlyph.svelte';
  import type { CardCounts } from '../../board-types';

  interface Props {
    totals: CardCounts;
    sentBack: number;
    colorIndex?: number;
  }
  let { totals, sentBack, colorIndex = 5 }: Props = $props();
  const pack = activePack();
</script>

<div class="sbkey" data-swarm-board-key>
  <span class="sbkey-label">{t('swarm.board.key')}</span>
  <span class="sbkey-item"><StatusGlyph column="todo" size={13} /><span class="sbkey-swatch sbkey-swatch--todo"></span>{t('swarm.board.key.todo', { count: totals.todo })}</span>
  <span class="sbkey-item"><StatusGlyph column="in_progress" size={13} /><span class="sbkey-swatch sbkey-swatch--in_progress"></span>{t('swarm.board.key.in_progress', { count: totals.in_progress })}</span>
  <span class="sbkey-item"><Character state="working" size={16} {colorIndex} {pack} still />{t('swarm.board.key.node')}</span>
  <span class="sbkey-item"><span class="sbkey-swatch sbkey-swatch--unrecorded"></span>{t('swarm.board.key.unrecorded')}</span>
  <span class="sbkey-item"><StatusGlyph column="review" size={13} /><span class="sbkey-swatch sbkey-swatch--review"></span>{t('swarm.board.key.review', { count: totals.review })}</span>
  <span class="sbkey-item"><StatusGlyph column="done" size={13} />{t('swarm.board.key.done', { count: totals.done })}</span>
  <span class="sbkey-item"><SentBackGlyph />{t('swarm.board.key.sent_back', { count: sentBack })}</span>
  <span class="sbkey-item">{t('swarm.board.key.hatched')}</span>
</div>

<style>
  @layer components {
    .sbkey {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px 22px;
      margin-top: 14px;
      padding-top: 14px;
      box-shadow: 0 -1px 0 var(--oc-line-rule);
      font-family: var(--font-mono);
    }
    .sbkey-label {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbkey-item {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
    }
    .sbkey-swatch {
      width: 18px;
      height: 8px;
      border-radius: 1px;
    }
    .sbkey-swatch--todo {
      width: 14px;
      height: 0;
      border-top: 1px dashed var(--oc-text-muted);
      border-radius: 0;
    }
    .sbkey-swatch--in_progress { background: var(--oc-yellow); }
    .sbkey-swatch--unrecorded { background: var(--oc-text-dim); }
    .sbkey-swatch--review { background: var(--oc-cyan); }
  }
</style>
