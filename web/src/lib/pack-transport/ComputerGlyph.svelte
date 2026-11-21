
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';

  const { kind }: { kind: 'self' | 'linked' | 'down' } = $props();
  const word = $derived(t(`pack.deck.glyph.${kind}`));
</script>

<span class="dk-glyph dk-glyph--link dk-glyph--{kind}" role="img" aria-label={word} title={word} data-link={kind}>
  <Icon name={kind === 'self' ? 'computer' : kind === 'linked' ? 'computers-linked' : 'computers-broken'} size={kind === 'self' ? 16 : 18} />
</span>
