
<script lang="ts">
  import { flushSync, tick } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import ListRow from '../../base/ListRow.svelte';
  import Mark from '../Mark.svelte';

  type Props = {
    kind: 'run' | 'fold' | 'member';
    rowKey: string;
    runId: string;
    status: string;
    name: string;
    where: string;
    time: string;
    trigger: string;
    faceText: string;
    faceTitle: string;
    took: string;
    size: string;
    selected: boolean;
    unread: boolean;
    changed: boolean;
    same: boolean;
    first: boolean;
    expanded: boolean;
    entering: boolean;
    ticked: boolean;
    refitTick: number;
    onPick: (rowKey: string) => void;
  };
  let { kind, rowKey, runId, status, name, where, time, trigger, faceText, faceTitle, took, size, selected, unread, changed, same, first, expanded, entering, ticked, refitTick, onPick }: Props = $props();

  const fitMode = $derived(/\S{26,}|\S*[/.]\S*[/.]\S*[/.]/.test(faceText));
  let el: HTMLElement | undefined = $state();
  let shown = $state<string | null>(null);

  function fit(): void {
    if (!fitMode || !el) {
      shown = null;
      return;
    }
    flushSync(() => (shown = null));
    if (!el.clientWidth) return;
    const node = el;
    const max = parseFloat(getComputedStyle(node).lineHeight) * 2 + 1;
    const over = (): boolean => node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > max;
    if (!over()) return;
    const words = faceText.split(/\s+/);
    let lo = 0;
    let hi = words.length - 1;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      flushSync(() => (shown = `${words.slice(0, mid).join(' ')}…`));
      if (over()) hi = mid - 1;
      else lo = mid;
    }
    flushSync(() => (shown = lo ? `${words.slice(0, lo).join(' ')}…` : '…'));
  }

  // not allowed
  $effect(() => {
    void faceText;
    void fitMode;
    void refitTick;
    void tick().then(fit);
  });
</script>


<!-- svelte-ignore a11y_interactive_supports_focus, a11y_click_events_have_key_events, a11y_role_supports_aria_props -->
<ListRow
  class={kind === 'member' ? 'ap-fd-r ap-fd-m' : 'ap-fd-r'}
  role="option"
  id={`e-${rowKey}`}
  data-key={rowKey}
  data-run={runId}
  data-kind={kind}
  data-status={status}
  data-chg={changed && kind === 'run' ? '' : undefined}
  data-same={same && kind === 'run' ? '' : undefined}
  data-unread={unread ? '' : undefined}
  data-entering={entering ? '' : undefined}
  data-tick={ticked ? '' : undefined}
  {selected}
  aria-selected={selected}
  aria-current={selected ? 'true' : undefined}
  aria-expanded={kind === 'fold' ? expanded : undefined}
  onclick={() => onPick(rowKey)}
>
  <span class="ap-fd-t ap-num">{time}</span>
  <span class="ap-fd-mk"><Mark {status} size={10} /></span>
  <span class="ap-fd-nm"><span class="ap-fd-n1" title={kind === 'member' ? undefined : name}>{name}</span></span>
  <span class="ap-fd-wh" title={t('automations.page.feed.files_under', { where })}>{where}</span>
  <span class="ap-fd-f" title={faceTitle}>
    {#if trigger && kind !== 'member'}<em class="ap-fd-tg">{trigger}</em>{/if}
    {#if kind === 'fold'}<i class="ap-fd-car" aria-hidden="true">{expanded ? '▾' : '▸'}</i>
    {:else if changed && kind === 'run' && !first}<i class="ap-fd-chg" title={t('automations.page.feed.changed_title')}>{'Δ'}</i>{/if}
    <span class="ap-fd-ft" data-fit={fitMode ? '' : undefined} bind:this={el}>{shown ?? faceText}</span>
  </span>
  <span class="ap-fd-tk ap-num">{took}</span>
  <span class="ap-fd-sz ap-num">{size}</span>
</ListRow>
