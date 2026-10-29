<script lang="ts">
  import { Segmented } from '../base';
  import { t } from '../i18n/index.svelte';
  import { LAYOUTS, type Layout } from './result-model';

  interface Props {
    value: Layout;
    onChange: (layout: Layout) => void;
  }
  let { value, onChange }: Props = $props();

  const OPTIONS = $derived(
    LAYOUTS.map((option) => ({ value: option, label: t(`deepsearch.layout.${option}`), attrs: { 'data-layout': option, title: t(`deepsearch.layout.${option}_tip`) } })),
  );
</script>


<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="dps__seg" data-testid="deepsearch-layout" onmousedown={(e) => e.preventDefault()}>
  <Segmented
    label={t('deepsearch.layout.label')}
    value={value}
    options={OPTIONS}
    onchange={(next) => onChange(next as Layout)}
  />
</div>
