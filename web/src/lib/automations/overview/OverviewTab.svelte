
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import State from '../../base/State.svelte';
  import { haystackOf } from '../list-state.svelte';
  import { TEMPLATES } from '../logic/templates';
  import { data, refresh, setPaused } from '../page-store.svelte';
  import { unread } from '../read-state.svelte';
  import './overview.css';
  import CadenceColumn from './CadenceColumn.svelte';
  import { columns } from './overview-model';
  import { overview, startBlank, startTemplate } from './overview-state.svelte';
  import Tiles from './Tiles.svelte';

  const state = $derived({ seenAt: unread.seenAt, read: new Set(unread.read) });
  const q = $derived(overview.find.trim().toLowerCase());
  const cols = $derived(columns(data.automations.filter((a) => !q || haystackOf(a).includes(q))));
</script>

<div class="t-pane" data-ap-overview>
  <Tiles />
  {#if data.status === 'loading'}
    <State kind="loading" title={t('automations.loading')} />
  {:else if data.status === 'error'}
    <State kind="error" title={t('automations.simple.read_failed')} hint={data.error} data-overview-error>
      {#snippet actions()}<Button size="sm" data-overview-retry onclick={() => void refresh()}>{t('automations.simple.retry')}</Button>{/snippet}
    </State>
  {:else}
    {#if data.paused}
      <State kind="warn" inline title={t('automations.simple.paused.strip')} data-overview-paused>
        {#snippet actions()}<Button size="sm" onclick={() => void setPaused(false)}>{t('automations.simple.paused.resume')}</Button>{/snippet}
      </State>
    {/if}
    {#if data.automations.length === 0}
      <State title={t('automations.simple.empty.title')} hint={t('automations.simple.empty.body')} data-overview-empty>
        {#snippet actions()}
          <Button variant="confirm" disabled={data.targets === null} onclick={startBlank}>{t('automations.new')}</Button>
          <div class="t-chips" role="group" aria-label={t('automations.simple.empty.chips_aria')}>
            {#each TEMPLATES.slice(0, 3) as tpl (tpl.id)}
              <Button size="sm" disabled={data.targets === null} data-template={tpl.id} onclick={() => startTemplate(tpl)}>
                {t(`automations.page.template.${tpl.id}.name`)}
              </Button>
            {/each}
          </div>
        {/snippet}
      </State>
    {:else if q && cols.often.length + cols.slow.length === 0}
      <State title={t('automations.simple.find.none')} data-overview-nomatch>
        {#snippet actions()}<Button size="sm" onclick={() => (overview.find = '')}>{t('automations.simple.find.clear')}</Button>{/snippet}
      </State>
    {:else}
      <div class="t-cols">
        <CadenceColumn id="often" rows={cols.often} unread={state} />
        <CadenceColumn id="slow" rows={cols.slow} unread={state} />
      </div>
    {/if}
  {/if}
</div>
