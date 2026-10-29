<script lang="ts">
  import { huddle } from '../../../cplugs/huddle/huddle.svelte';
  import './mk2-design.css';
  import { useFrameHeader } from '../../shell/frame-header.svelte';
  import Icon from '../../ui/Icon.svelte';
  import { MK2_CHIP_ICON } from './mk2-chips';
  import { allEntriesOf, groupEntriesOf, headCountText, headCountsOf, listEntriesOf, needsYouText } from './mk2-head-count';

  let { list }: { list: string | null } = $props();

  const frame = useFrameHeader();
  const entries = $derived(list === null ? allEntriesOf(huddle.groups) : listEntriesOf(huddle.body, list) ?? groupEntriesOf(huddle.groups, list));
  const counts = $derived(entries === null ? null : headCountsOf(entries));
  const shown = $derived(
    counts === null
      ? []
      : [
          { key: 'needs-you', n: counts.needsYou, words: needsYouText(counts.needsYou), icon: MK2_CHIP_ICON.needs_you },
          { key: 'unread', n: counts.unread, words: headCountText(counts.unread), icon: MK2_CHIP_ICON.unread },
        ].filter((one) => one.n > 0),
  );

  $effect(() => {
    if (!frame) return;
    frame.action = counter;
    return () => { if (frame.action === counter) frame.action = null; };
  });
</script>

{#snippet counter()}{#each shown as one (one.key)}<span class="tm-head-count mk2-head-n" role="group" aria-label={one.words} title={one.words} data-mk2-head-count={one.key}><span class="mk2-head-ico" aria-hidden="true"><Icon name={one.icon} size={12} strokeWidth={2} /></span><span class="mk2-head-num" aria-hidden="true">{one.n}</span><span class="mk2-head-words">{one.words}</span></span>{/each}{/snippet}
