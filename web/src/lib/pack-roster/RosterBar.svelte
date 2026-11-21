
<script lang="ts">
  import './roster.css';
  import { t } from '../i18n/index.svelte';
  import SearchField from '../../opscenter/ui/SearchField.svelte';
  import FacetSelect from '../../opscenter/ui/FacetSelect.svelte';
  import ViewToggle from '../manager-frame/ViewToggle.svelte';
  import { rosterUi } from './roster-ui.svelte';
  import type { SortKey } from './roster-model';

  const sortOptions = $derived((['status', 'name', 'free', 'seen'] as const).map((k) => ({ value: k, label: t(`roster.sort.${k}`) })));
</script>

<div class="oc-toolbar rs-bar" role="search">
  <div class="oc-toolbar__search"><SearchField value={rosterUi.q} onInput={(v) => (rosterUi.q = v)} placeholder={t('roster.find.placeholder')} ariaLabel={t('roster.find.placeholder')} /></div>
  <div class="oc-toolbar__end">
    <FacetSelect id="sort" label={t('roster.sort.label')} options={sortOptions} value={rosterUi.sort} onChange={(v) => (rosterUi.sort = v as SortKey)} />
    <ViewToggle view={rosterUi.view === 'list' ? 'list' : 'grid'} onView={(v) => (rosterUi.view = v === 'list' ? 'list' : 'cards')} {t} shelf />
  </div>
</div>
