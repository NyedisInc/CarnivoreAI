
<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { apiErrorMessageOr } from '../errors/failure-reason';
  import { computers } from '../computers/computers-store.svelte';
  import { packMachines } from '../pack-machines/pack-machines-store.svelte';
  import { agoText } from '../publish-page/format';
  import RotateWalk from './RotateWalk.svelte';
  import { readRemovedLogins, statusNow, statusWords, STATUS_LOOK, type RemovedLogins } from './removed-logins';

  const { nowMs }: { nowMs: number } = $props();
  let data = $state<RemovedLogins | null>(null);
  let problem = $state<string | null>(null);
  const ids = $derived([...(computers.data?.computers ?? []).map((c) => c.install_id).sort(), '|', ...(packMachines.data?.machines ?? []).map((m) => m.install_id).sort()].join(','));

  async function load(): Promise<void> {
    try { data = await readRemovedLogins(); problem = null; } catch (e) { problem = apiErrorMessageOr(e, t('api.error.removed_logins_unavailable')); }
  }
  let first = true;
  onMount(() => { void load(); });
  $effect(() => { void ids; if (first) { first = false; return; } void load(); });
</script>

<section class="m1-sec" data-sec="removed-logins"><h3 class="pp-k">{t('pack.removed_logins.title')}</h3>
  <p class="pp-hint">{t('pack.removed_logins.help')} {t('pack.removed_logins.this_only')}</p>
  {#if problem}<p class="pp-err" role="alert">{problem}</p>{/if}
  {#if data}
    {#if data.computers.length === 0}<p class="pp-hint">{t('pack.removed_logins.empty')}</p>{/if}
    {#each data.computers as removed (removed.install_id)}
      <ul class="pp-grants">
        <li class="pp-swrow" data-removed={removed.install_id}><span>{removed.label ? t('pack.removed_logins.computer_named', { name: removed.label }) : t('pack.removed_logins.computer', { id: removed.install_id.slice(0, 8) })}</span>
          <span class="pp-dim">{agoText(removed.removed_at, nowMs, t)}</span></li>
        {#each removed.copies as copy, i (i)}
          {@const look = STATUS_LOOK[statusNow(copy, nowMs)]}
          <li class="pp-swrow" data-copy><span>{t(`pack.removed_logins.kind.${copy.kind}`)}{#if copy.account}{' '}<span class="pp-dim">{copy.account}</span>{/if}</span>
            <span class="pp-st" data-shape={look.shape} data-tone={look.tone}><i class="pp-st__mark" aria-hidden="true"></i><span class="pp-st__word">{statusWords(copy, nowMs)}</span></span></li>
        {/each}
      </ul>
    {/each}
    {#if !data.argent_known}<p class="pp-hint">{t('pack.removed_logins.argent_unknown')}</p>{/if}
    {#if data.not_tracked.includes('github')}<p class="pp-hint">{t('pack.removed_logins.github_untracked')}</p>{/if}
  {/if}
  <RotateWalk {nowMs} />
</section>
