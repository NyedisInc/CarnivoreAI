<script lang="ts">
  import { Segmented } from '../base';
  import { t } from '../i18n/index.svelte';
  import { SORTS, type SortChoice } from './result-model';

  interface Props {
    value: SortChoice;
    onChange: (sort: SortChoice) => void;
  }
  let { value, onChange }: Props = $props();

  const OPTIONS = $derived(
    SORTS.map((option) => ({ value: option, label: t(`deepsearch.sort.${option}`), attrs: { 'data-sort': option, title: t(`deepsearch.sort.${option}_tip`) } })),
  );
</script>


<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="dps__seg" data-testid="deepsearch-sort" onmousedown={(e) => e.preventDefault()}>
  <Segmented
    label={t('deepsearch.sort.label')}
    value={value}
    options={OPTIONS}
    onchange={(next) => onChange(next as SortChoice)}
  />
</div>
