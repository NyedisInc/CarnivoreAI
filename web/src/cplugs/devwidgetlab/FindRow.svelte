<script lang="ts">
  import { t } from '../sdk';
  import { Icon } from '../sdk/ui';
  import type { ResultFilter } from './lab-model';

  interface Props {
    query: string;
    result: ResultFilter;
    hasTable: boolean;
    failing: number;
    unchecked: number;
  }

  let { query = $bindable(), result = $bindable(), hasTable, failing, unchecked }: Props = $props();
</script>

<div class="dwl-filter">
  <label class="dwl-search">
    <Icon name="search" size={12} />
    <input class="oc-field" type="search" placeholder={t('cplug.devwidgetlab.filter.placeholder')} aria-label={t('cplug.devwidgetlab.filter.placeholder')}
      bind:value={query} onkeydown={(event) => { if (event.key === 'Escape' && query !== '') { query = ''; event.stopPropagation(); } }} />
  </label>
  <select class="oc-field dwl-result" aria-label={t('cplug.devwidgetlab.filter.results')} value={result}
    onchange={(event) => (result = event.currentTarget.value as ResultFilter)}>
    <option value="all">{t('cplug.devwidgetlab.filter.all')}</option>
    <option value="failing" disabled={!hasTable} title={hasTable ? undefined : t('cplug.devwidgetlab.filter.no_run')}>{t('cplug.devwidgetlab.filter.failing', { count: failing })}</option>
    <option value="unchecked">{t('cplug.devwidgetlab.filter.unchecked', { count: unchecked })}</option>
  </select>
</div>
