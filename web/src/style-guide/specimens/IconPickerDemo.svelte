<script lang="ts">
  import IconPicker from '../../lib/icon-picker/IconPicker.svelte';
  import IconMark from '../../lib/icon-picker/IconMark.svelte';
  import type { Translate } from '../../lib/sessions/types';
  import { t as catalogT } from '../../lib/i18n/index.svelte';

  let {
    initial = 'folder',
    tone = '--oc-green',
    t = catalogT,
  }: { initial?: string | null; tone?: string; t?: Translate } = $props();

  // svelte-ignore state_referenced_locally
  let value = $state<string | null>(initial);
</script>


<div
  data-sg-icp
  style:color={`var(${tone})`}
  style:display="flex"
  style:flex-direction="column"
  style:gap="10px"
>
  <p
    data-sg-icp-heading
    style:display="flex"
    style:align-items="center"
    style:gap="6px"
    style:margin="0"
    style:font-size="11px"
    style:letter-spacing="0.6px"
    style:text-transform="uppercase"
  >
    <IconMark id={value} size={12} /><span>research</span>
  </p>
  <IconPicker {value} {t} onChange={(id) => { value = id; }} />
</div>
