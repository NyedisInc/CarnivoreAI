<script lang="ts">
  /* could not selected widget */
  import { t } from '../sdk';
  import { Icon } from '../sdk/ui';
  import type { CheckScope } from './lab-selection';
  import OptionChip from './OptionChip.svelte';
  import type { MatrixRunner } from './matrix-runner.svelte';

  interface Props {
    runner: MatrixRunner;
    scope: CheckScope;
    selected: string | null;
    total: number;
    onshow: () => void;
  }

  let { runner, scope = $bindable(), selected, total, onshow }: Props = $props();

  let catalog = $state(false);
  const snap = $derived(runner.state);
  const counts = $derived(snap?.table?.counts ?? null);
  const effective = $derived(scope === 'selected' && selected !== null ? 'selected' : 'all');
  const idle = $derived(!snap?.available || snap?.running === true);
  const summary = $derived.by(() => {
    if (snap?.running) return { text: t('cplug.devwidgetlab.checks.running'), tone: undefined };
    if (!counts) return { text: t('cplug.devwidgetlab.checks.not_checked'), tone: undefined };
    return { text: t('cplug.devwidgetlab.fit.counts', { pass: counts.pass, fail: counts.fail, unsupported: counts.unsupported }), tone: counts.fail > 0 ? 'bad' : 'ok' };
  });
</script>

<div class="dwl-checks">
  <div class="dwl-row">
    <label class="dwl-label" for="dwl-scope">{t('cplug.devwidgetlab.checks.scope')}</label>
    <select id="dwl-scope" class="oc-field" value={effective} onchange={(event) => (scope = event.currentTarget.value === 'selected' ? 'selected' : 'all')}>
      <option value="all">{t('cplug.devwidgetlab.checks.scope_all', { count: total })}</option>
      <option value="selected" disabled={selected === null}>{t('cplug.devwidgetlab.checks.scope_selected')}</option>
    </select>
  </div>
  <div class="dwl-run-row">
    <button type="button" class="oc-btn oc-btn--confirm" data-run-checks disabled={idle} title={snap && !snap.available ? t(`cplug.devwidgetlab.capture.unavailable.${snap.reason || 'unknown'}`) : undefined} onclick={() => void runner.run(catalog, effective === 'selected' ? selected : null)}>
      <Icon name="play" size={12} />{t('cplug.devwidgetlab.checks.run')}</button>
    <button type="button" class="oc-btn" data-show-results onclick={onshow}>{t('cplug.devwidgetlab.checks.results')}<Icon name="external" size={12} /></button>
  </div>
  <p class="dwl-note" data-summary data-tone={summary.tone}>{summary.text}</p>
  {#if runner.refusal}<p class="dwl-note dwl-note--error">{runner.refusal}</p>{/if}
  {#if snap && !snap.running && snap.exit === 2}<p class="dwl-note dwl-note--error">{t('cplug.devwidgetlab.fit.undetermined')}</p>{/if}
  <OptionChip bare label={t('cplug.devwidgetlab.fit.catalog')} checked={catalog} onpick={() => (catalog = !catalog)} />
  <p class="dwl-note dwl-note--muted">{t('cplug.devwidgetlab.checks.covers')}</p>
</div>
