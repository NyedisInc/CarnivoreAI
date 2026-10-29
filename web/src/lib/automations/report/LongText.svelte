
<script lang="ts">
  import Button from '../../base/Button.svelte';
  import { t } from '../../i18n/index.svelte';
  import { stringShape } from '../logic/report-rules';
  import Markdown from './Markdown.svelte';

  let { text, truncated = false }: { text: string; truncated?: boolean } = $props();
  let expanded = $state(false);
  const shape = $derived(stringShape(text));
</script>

{#if shape.blank}
  <span class="r-null">{t('automations.page.report.no_output')}</span>
{:else if !shape.long || expanded}
  {#if shape.markdown}<Markdown src={shape.text} />{:else}<pre class="r-pre">{shape.text.replace(/\s+$/, '')}</pre>{/if}
{:else}
  <div class="r-clip" data-clip>
    <pre class="r-pre">{shape.head.join('\n')}{'\n'}{#if shape.cut > 0}{t('automations.page.report.lines_not_shown', { n: shape.cut })}{'\n'}{/if}{shape.tail.join('\n')}</pre>
    <div class="r-clipbar">
      <Button size="sm" data-r-expand onclick={() => (expanded = true)}>{t('automations.page.report.show_all_lines', { n: shape.lineCount })}</Button>
      {#if truncated}<span class="r-note">{t('automations.page.report.truncated')}</span>{/if}
    </div>
  </div>
{/if}
