
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { tagClass, type TagTone } from './classes';

  import type { HTMLAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLAttributes<HTMLSpanElement>, 'class' | 'children'> {
    tone?: TagTone;
    children: Snippet;
  }

  let { tone = 'neutral', children, ...rest }: Props = $props();
</script>

<span class={tagClass(tone)} {...rest}>{@render children()}</span>
