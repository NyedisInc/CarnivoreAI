<script lang="ts">
  /* one click opens the context */
  import Icon from '../../opscenter/ui/Icon.svelte';
  import HitText from './HitText.svelte';
  import ConvTags from './ConvTags.svelte';
  import type { DeepGroup, DeepHit } from './deepsearch-api';
  import type { ConvState } from './result-model';
  import './search-d.css';

  interface Props {
    hit: DeepHit;
    group: DeepGroup;
    conv: ConvState;
    tags?: boolean;
    name: string;
    when: string;
    id: string;
    picked: boolean;
    onopen: () => void;
  }
  let { hit, group, conv, tags = true, name, when, id, picked, onopen }: Props = $props();
</script>

<div {id} class="sd-hit dps__prompt" class:is-focus={picked} role="option" tabindex="-1" aria-selected={picked}
  onmousedown={(e) => e.preventDefault()} onclick={onopen} onkeydown={() => undefined}>
  <div class="sd-hit__top"><span class="sd-glyph dps__prompt-glyph"><Icon name="prompt" size={12} /></span><span class="sd-hit__name">{name}</span>{#if tags}<ConvTags {group} {conv} />{/if}<span class="sd-r__meta">{when}</span></div>
  <div class="sd-hit__snip"><HitText snippet={hit.snippet} /></div>
</div>
