
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';

  let { text, eg = '', onFill, field = '' }: { text: string; eg?: string; onFill?: (eg: string) => void; field?: string } = $props();
</script>

<span class="w-hint" data-hint={field || undefined}>
  {text}
  {#if eg}<span class="w-egl">{t('automations.simple.hint.eg')} <Button variant="quiet" size="sm" data-w-fill={field || undefined} title={t('automations.simple.hint.eg_title')} onclick={() => onFill?.(eg)}>{eg}</Button></span>{/if}
</span>
