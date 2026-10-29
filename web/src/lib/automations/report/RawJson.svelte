
<script lang="ts">
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import { t } from '../../i18n/index.svelte';

  let { report }: { report: unknown } = $props();
  const LIMIT = 60000;
  const text = $derived(report === null || report === undefined ? 'null' : JSON.stringify(report, null, 2));
  const cut = $derived(text.length > LIMIT);
  let open = $state(false);
  let label = $state<string | null>(null);
  let timer: ReturnType<typeof setTimeout> | null = null;

  function flip(ok: boolean): void {
    label = ok ? t('automations.page.report.copied') : t('automations.page.report.select_text');
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => (label = null), 1200);
  }
  function copy(): void {
    try {
      navigator.clipboard.writeText(text).then(() => flip(true), () => flip(false));
    } catch {
      flip(false);
    }
  }
</script>

<Card title={t('automations.page.report.raw')} foldable bind:open data-part="raw">
  <div class="r-rawbar">
    <Button size="sm" data-copy onclick={copy}>{label ?? t('automations.page.report.copy')}</Button>
    {#if cut}<span class="r-note">{t('automations.page.report.raw_cut', { n: text.length.toLocaleString('en-US') })}</span>{/if}
  </div>
  <pre class="r-pre">{cut ? text.slice(0, LIMIT) : text}</pre>
</Card>
