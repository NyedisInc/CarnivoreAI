
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Tag from '../../base/Tag.svelte';
  import { tagToneOf } from '../overview/overview-model';
  import Mark from '../Mark.svelte';
  import type { RunWord } from './review-model';

  type Props = {
    runId: string;
    status: string;
    name: string;
    clock: string;
    word: RunWord;
    title: string;
    summary: string;
    reviewed: boolean;
    selected: boolean;
    entering: boolean;
    leaving: boolean;
    onOpen: (id: string) => void;
    onGood: (id: string) => void;
  };
  let { runId, status, name, clock, word, title, summary, reviewed, selected, entering, leaving, onOpen, onGood }: Props = $props();

  function click(e: MouseEvent): void {
    if ((e.target as HTMLElement).closest('button')) return;
    onOpen(runId);
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
  class="f-row"
  role="row"
  tabindex="-1"
  data-run={runId}
  data-reviewed={reviewed}
  data-sel={selected ? '' : undefined}
  data-entering={entering ? '' : undefined}
  data-fold={leaving ? '' : undefined}
  onclick={click}
>
  <div class="f-t">{clock}</div>
  <div class="f-sp"><span class="f-dot"><Mark {status} size={12} /></span></div>
  <div class="f-body">
    <span class="f-time-in">{clock}</span>
    <div class="f-who">
      <span class="f-auto">{name}</span>
      <Tag tone={tagToneOf(word.tone)}>{t(`automations.simple.row.word.${word.key}`)}</Tag>
    </div>
    <Button variant="row" data-run-title onclick={() => onOpen(runId)}>{title}</Button>
    {#if summary}<div class="f-sum">{summary}</div>{/if}
  </div>
  <div class="f-act">
    {#if reviewed || leaving}
      <span class="t-quiet">{t('automations.simple.row.reviewed')}</span>
    {:else}
      <Button size="sm" data-good={runId} onclick={() => onGood(runId)}>{t('automations.simple.row.good')}</Button>
    {/if}
  </div>
</div>
