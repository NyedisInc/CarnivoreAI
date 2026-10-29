<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
  import { setReviewCheck } from '../../../cplugs/huddle/huddle.svelte';
  import OptionList, { type OptionItem } from '../../../lib/base/OptionList.svelte';
  import { tickedLine } from './mk2-review-checks';

  let { item }: { item: HuddleItem } = $props();

  const checks = $derived(item.review_checks ?? []);
  const options = $derived<OptionItem[]>(checks.map((c) => ({
    value: String(c.id),
    label: c.label,
    ...(c.checked ? { reason: tickedLine(c, (key, args) => t(key, args)) } : {}),
  })));
  const ticked = $derived(checks.filter((c) => c.checked).map((c) => String(c.id)));

  function onChange(next: string | string[]): void {
    const now = new Set(Array.isArray(next) ? next : [next]);
    for (const c of checks) {
      const on = now.has(String(c.id));
      if (on !== !!c.checked) { void setReviewCheck(item, c.id, on); return; }
    }
  }
</script>

{#if checks.length}
  <div class="mk2-checks" data-mk2-checks={item.id}>
    <OptionList multiple prompt={t('opscenter.cell.task_manager_mk2.checks_title')} {options} value={ticked} onValueChange={onChange} />
  </div>
{/if}

<style>
  @layer components {
    .mk2-checks {
      min-width: 0;
      margin-top: var(--oc-space-2);
    }
  }
</style>
