
<script lang="ts">
  import Button from '../base/Button.svelte';
  import { t } from '../i18n/index.svelte';
  import type { DiffResult } from './logic/diff';
  import { compareWithPrevious, lineFor } from './list-state.svelte';
  import { data, openPane } from './page-store.svelte';

  const auto = $derived(data.automations.find((a) => a.automation_id === data.selectedId) ?? null);
  const run = $derived.by(() => {
    const recent = auto?.recent ?? [];
    const stepped = data.paneOpen && data.paneRunId ? recent.find((r) => r.run_id === data.paneRunId) : undefined;
    return stepped ?? recent[0] ?? null;
  });
  let cmp = $state<{ id: string; result: DiffResult | null } | null>(null);

  $effect(() => {
    const a = auto;
    const r = run;
    if (!a || !r || (r.status !== 'succeeded' && r.status !== 'failed')) {
      cmp = null;
      return;
    }
    const id = r.run_id;
    void compareWithPrevious(a.automation_id, r).then((result) => {
      if (run?.run_id === id) cmp = { id, result };
    });
  });

  const text = $derived(run ? lineFor(run, cmp && cmp.id === run.run_id ? cmp.result : null) : '');
  const calm = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
</script>

<div class="ap-pv" data-auto-preview aria-live="polite">
  <span class="pl-label">{t('automations.page.preview.label')}</span>
  {#if auto}<span class="ap-pv__name">{auto.name}</span>{/if}
  {#key `${auto?.automation_id ?? ''}|${text}`}
    <span class="ap-pv__line ap-num" class:ap-fade={!calm}>{!auto ? t('automations.page.preview.select') : text || t('automations.page.preview.none')}</span>
  {/key}
  {#if auto}
    <Button size="sm" data-pv-open onclick={() => openPane()}>
      {t(data.paneOpen ? 'automations.page.preview.in_pane' : 'automations.page.preview.open')}
    </Button>
  {/if}
</div>
