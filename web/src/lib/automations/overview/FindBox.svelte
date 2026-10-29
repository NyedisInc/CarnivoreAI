
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Field from '../../base/Field.svelte';
  import { data } from '../page-store.svelte';
  import { showFind } from './overview-model';
  import { overview } from './overview-state.svelte';
</script>

{#if data.top === 'automations' && showFind(data.automations.length)}
  <div class="t-find">
    <Field
      variant="search"
      label={t('automations.simple.find.aria')}
      bind:value={overview.find}
      data-overview-find
      placeholder={t('automations.simple.find.placeholder')}
      clearLabel={t('automations.simple.find.clear')}
      autocomplete="off"
      spellcheck={false}
    />
  </div>
{/if}
