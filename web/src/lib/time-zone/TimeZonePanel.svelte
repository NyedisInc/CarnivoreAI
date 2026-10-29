
<script lang="ts">
  import { onDestroy } from 'svelte';
  import { Field, Radio, RadioGroup } from '../base';
  import { t as reactiveT } from '../i18n/index.svelte';
  import type { Translate } from '../sessions/types';
  import '../settings-page/panel-kit/panel-kit.css';
  import { filterZones, followTimeZone, readTimeZone, saveTimeZone, supportedZones } from './time-zone';

  interface Props {
    t?: Translate;
  }
  const { t = reactiveT }: Props = $props();

  const zones = supportedZones();
  let zone = $state(readTimeZone());
  let query = $state('');
  let saving = $state(false);
  let problem = $state('');
  const shown = $derived(filterZones(zones, query));

  const stop = followTimeZone((next) => {
    zone = next;
  });
  onDestroy(stop);

  async function pick(next: string): Promise<void> {
    const before = zone;
    if (next === before || saving) return;
    zone = next;
    saving = true;
    const why = await saveTimeZone(next);
    saving = false;
    if (why) {
      zone = before;
      problem = t('time_zone.error.save', { reason: why === 'unavailable' ? t('time_zone.unavailable') : why });
    } else {
      problem = '';
    }
  }
</script>

<div class="tm" data-time-zone="panel">
  <p class="tm__sub" data-time-zone="current">{t('time_zone.current', { zone })}</p>
  <Field
    type="search"
    block
    bind:value={query}
    placeholder={t('time_zone.search_placeholder')}
    aria-label={t('time_zone.search_label')}
    data-time-zone="search"
    autocomplete="off"
    spellcheck="false"
  />
  <div class="restart-picker__options" aria-busy={saving} data-time-zone="list">
    <RadioGroup label={t('time_zone.search_label')} value={zone} name="time-zone" disabled={saving} onchange={(name) => void pick(name)}>
      {#each shown as name (name)}
        <Radio value={name} label={name} data-time-zone-name={name} />
      {/each}
    </RadioGroup>
    {#if shown.length === 0}
      <p class="tm__sub" data-time-zone="none">{t('time_zone.none')}</p>
    {/if}
  </div>
  <p class="tm__note" data-time-zone="note">{t('time_zone.note')}</p>
  {#if saving}<p class="tm__sub" role="status">{t('time_zone.saving')}</p>{/if}
  {#if problem}<p class="tm__problem" role="alert">{problem}</p>{/if}
</div>
