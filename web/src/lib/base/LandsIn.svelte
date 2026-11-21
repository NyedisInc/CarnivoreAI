
<script lang="ts" module>
  export interface LandsLine {
    level: 'ok' | 'warn' | 'block';
    word: string;
    text: string;
  }
</script>

<script lang="ts">
  import type { HTMLAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLAttributes<HTMLDivElement>, 'class' | 'children'> {
    lines: readonly LandsLine[];
    label: string;
  }

  let { lines, label, ...rest }: Props = $props();
</script>

<div {...rest} class="oc-lands" role="status" aria-live="polite" aria-label={label}>
  {#each lines as line, i (i)}
    <div class="oc-lands__line" data-level={line.level}>
      <span class="oc-lands__level">{line.word}</span>
      <span class="oc-lands__text">{line.text}</span>
    </div>
  {/each}
</div>
