<!-- hidden -->
<script lang="ts">
  import Button from '../../base/Button.svelte';
  import Switch from '../../base/Switch.svelte';
  import { t } from '../../i18n/index.svelte';
  import CommandsPopover from '../CommandsPopover.svelte';
  import { data, sentence, setPaused } from '../page-store.svelte';
  import './advanced.css';
</script>

<div class="pl-titlebar ap-adv-head" data-ap-advanced-head>
  <h1 class="pl-title">{t('automations.simple.adv.title')}</h1>
  <span class="ap-sum ap-num ap-adv-sum" role="status" data-header-sentence>{sentence()}</span>
  <div class="ap-acts">
    <Button data-automation-log-toggle aria-expanded={data.logOpen} onclick={() => (data.logOpen = !data.logOpen)}>
      {t('automations.log.show')}
    </Button>
    <CommandsPopover />
    <Switch
      label={t('automations.scheduler_paused.switch')}
      checked={data.paused}
      aria-label={t('automations.scheduler_paused.switch_aria')}
      data-scheduler-pause-switch
      onchange={(next) => void setPaused(next)}
    />
  </div>
</div>
{#if data.paused}<p class="ap-strip" role="status" data-scheduler-paused>{t('automations.scheduler_paused.banner')}</p>{/if}
