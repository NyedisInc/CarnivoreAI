
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import Card from '../base/Card.svelte';
  import Tag from '../base/Tag.svelte';
  import type { PackComputer } from './activity-api';

  interface Props {
    computers: PackComputer[];
    selected: string;
    days: number;
    onSelect: (installId: string) => void;
  }
  const { computers, selected, days, onSelect }: Props = $props();

  const barLevel = (pct: number | null): 'ok' | 'warn' | 'hot' => {
    if (pct === null) return 'ok';
    if (pct >= 80) return 'hot';
    if (pct >= 60) return 'warn';
    return 'ok';
  };
  const clampPct = (pct: number | null): number => Math.max(0, Math.min(100, Math.round(pct ?? 0)));
  const toggle = (id: string): void => onSelect(selected === id ? '' : id);
</script>

{#if computers.length > 0}
  <div class="pa-section" data-activity="computers">
    <div class="pa-section__head">
      <h3 class="pa-section__title">{t('pack.activity.distribution.title')}</h3>
      {#if selected}
        <Button size="sm" data-activity="clear-computer" onclick={() => onSelect('')}>{t('pack.activity.filter.all_computers')}</Button>
      {:else}
        <span class="pa-section__count">{t('pack.activity.distribution.hint')}</span>
      {/if}
    </div>
    <div class="pa-computers">
      {#each computers as comp (comp.install_id)}
        {@const isSelected = selected === comp.install_id}
        {@const liveJobs = comp.live_commands + comp.live_delegated_agents}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div
          class="pa-comp-wrap"
          data-computer={comp.install_id}
          data-selected={isSelected ? 'true' : 'false'}
          onclick={() => toggle(comp.install_id)}
        >
          <Card
            compact
            title={comp.label}
            meta={comp.cores ? `${comp.cores}c · ${comp.mem_total_gb ?? '?'}GB` : undefined}
            onopen={() => toggle(comp.install_id)}
          >
            {#snippet actions()}
              {#if comp.pegged}
                <Tag tone="danger">{t('pack.activity.computer.pegged')}</Tag>
              {:else if comp.is_self}
                <Tag tone="info">{t('pack.activity.computer.self')}</Tag>
              {:else if comp.online}
                <Tag tone="ok">{t('pack.activity.computer.online')}</Tag>
              {:else}
                <Tag tone="neutral">{t('pack.activity.computer.offline')}</Tag>
              {/if}
            {/snippet}
            {#snippet children()}
              <div class="pa-comp-body">
                <div class="pa-comp-counts" data-computer-counts={comp.install_id}>
                  <span class="pa-comp-metric">
                    <strong class="pa-comp-metric__num">{comp.live_agents}</strong>
                    <span class="pa-comp-metric__lbl">{t('pack.activity.computer.agents_now')}</span>
                  </span>
                  <span class="pa-comp-metric">
                    <strong class="pa-comp-metric__num">{liveJobs}</strong>
                    <span class="pa-comp-metric__lbl">{t('pack.activity.computer.jobs_now')}</span>
                  </span>
                </div>
                {#if comp.online}
                  <div class="pa-bars">
                    <div class="pa-bar">
                      <span>CPU</span>
                      <span class="pa-bar__track">
                        <span class="pa-bar__fill" data-level={barLevel(comp.cpu_pct)} style:width={`${clampPct(comp.cpu_pct)}%`}></span>
                      </span>
                      <span class="pa-bar__val">{comp.cpu_pct !== null ? `${Math.round(comp.cpu_pct)}%` : '-'}</span>
                    </div>
                    <div class="pa-bar">
                      <span>RAM</span>
                      <span class="pa-bar__track">
                        <span class="pa-bar__fill" data-level={barLevel(comp.ram_pct)} style:width={`${clampPct(comp.ram_pct)}%`}></span>
                      </span>
                      <span class="pa-bar__val">{comp.ram_pct !== null ? `${Math.round(comp.ram_pct)}%` : '-'}</span>
                    </div>
                  </div>
                {/if}
                <div class="pa-comp-foot">
                  <span>{t('pack.activity.computer.history_count', { count: String(comp.history_total), days: String(days) })}</span>
                  {#if comp.online && comp.cpu_headroom_cores !== null && comp.mem_headroom_gb !== null}
                    <span>{t('pack.activity.computer.free_short', { cores: String(Math.round(comp.cpu_headroom_cores * 10) / 10), ram: String(Math.round(comp.mem_headroom_gb * 10) / 10) })}</span>
                  {/if}
                </div>
              </div>
            {/snippet}
          </Card>
        </div>
      {/each}
    </div>
  </div>
{/if}
