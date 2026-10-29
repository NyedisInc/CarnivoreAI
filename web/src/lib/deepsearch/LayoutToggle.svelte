<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { LAYOUTS, type Layout } from './result-model';

  interface Props {
    value: Layout;
    onChange: (layout: Layout) => void;
  }
  let { value, onChange }: Props = $props();
</script>

<div class="oc-seg dps__seg" role="radiogroup" aria-label={t('deepsearch.layout.label')} data-testid="deepsearch-layout">
  {#each LAYOUTS as option (option)}
    <button type="button" class="oc-seg__item" role="radio" aria-checked={option === value} data-layout={option}
      title={t(`deepsearch.layout.${option}_tip`)} onmousedown={(e) => e.preventDefault()}
      onclick={() => onChange(option)}>{t(`deepsearch.layout.${option}`)}</button>
  {/each}
</div>
