
<script lang="ts">
  import Tabs, { panelAttrs, type TabDef } from '../../../opscenter/ui/Tabs.svelte';
  import { t } from '../../i18n/index.svelte';
  import AutoList from '../AutoList.svelte';
  import CounterStrip from '../CounterStrip.svelte';
  import FeedTab from '../feed/FeedTab.svelte';
  import { data, setTab } from '../page-store.svelte';
  import { ADVANCED_TABS } from '../tabs';
  import AdvancedHead from './AdvancedHead.svelte';
  import './advanced.css';

  const subTabs = $derived<TabDef[]>(
    ADVANCED_TABS.map((id) => ({ id, label: t(id === 'automations' ? 'automations.simple.adv.tab_table' : 'automations.simple.adv.tab_feed') })),
  );
</script>

<div class="ap-adv" data-ap-advanced>
  <AdvancedHead />
  <Tabs tabs={subTabs} active={data.tab} onSelect={(id) => setTab(id, true)} label={t('automations.simple.adv.tabs_aria')} idBase="automations-adv" class="ap-tabs ap-subtabs" />
  <CounterStrip />
  <div {...panelAttrs('automations-adv', data.tab)} class="ap-body">
    {#if data.status === 'loading'}
      <p class="ap-state" role="status">{t('automations.loading')}</p>
    {:else if data.status === 'error' && data.tab === 'sessions'}
      <p class="ap-state ap-state--error" role="alert" data-automations-error>{t('automations.read_failed', { reason: data.error })}</p>
    {:else if data.tab === 'sessions'}
      <FeedTab />
    {:else}
      <!-- the detail pane -->
      <div class="ap-tab" data-automations-tab><AutoList /></div>
    {/if}
  </div>
</div>
