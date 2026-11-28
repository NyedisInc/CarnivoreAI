
<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { apiErrorMessageOr } from '../errors/failure-reason';
  import { openModal } from '../modal';
  import Button from '../base/Button.svelte';
  import FedConfirmModal from '../hosts-page/FedConfirmModal.svelte';
  import { agoText } from '../publish-page/format';
  import { forgetLeftover, readLeftovers, rowCount, type Leftover } from './leftovers';

  const { nowMs }: { nowMs: number } = $props();
  let items = $state<Leftover[]>([]);
  let problem = $state<string | null>(null);
  let busy = $state(false);

  async function load(): Promise<void> {
    try { items = (await readLeftovers()).leftovers ?? []; problem = null; } catch (e) { problem = apiErrorMessageOr(e, t('api.error.leftovers_unavailable')); }
  }
  onMount(() => { void load(); });

  async function remove(item: Leftover): Promise<void> {
    const yes = await openModal<true, { title: string; body: string; confirmLabel: string }>(FedConfirmModal, {
      title: t('pack.leftovers.confirm_title'), body: t('pack.leftovers.confirm_body', { name: item.name }), confirmLabel: t('pack.leftovers.delete'),
    });
    if (!yes || busy) return;
    busy = true;
    try { await forgetLeftover(item.install_id); problem = null; } catch (e) { problem = apiErrorMessageOr(e, t('pack.leftovers.failed')); }
    finally { busy = false; await load(); }
  }
</script>

{#if items.length > 0 || problem}
  <section class="m1-sec" data-sec="leftovers"><h3 class="pp-k">{t('pack.leftovers.title')}</h3>
    <p class="pp-hint">{t('pack.leftovers.help')}</p>
    {#if problem}<p class="pp-err" role="alert">{problem}</p>{/if}
    <ul class="pp-grants">
      {#each items as item (item.install_id)}
        <li class="pp-swrow" data-leftover={item.install_id}><span>{item.name}</span>
          {#if item.newest_at !== null}<span class="pp-dim">{t('pack.leftovers.last_seen', { age: agoText(item.newest_at * 1000, nowMs, t) })}</span>{/if}
          <span class="pp-dim">{t('pack.leftovers.rows', { count: rowCount(item) })}</span>
          <Button variant="danger" size="sm" data-act="delete-leftover" disabled={busy} aria-label={t('pack.leftovers.delete_aria', { name: item.name })}
            onclick={() => void remove(item)}>{t('pack.leftovers.delete')}</Button></li>
      {/each}
    </ul>
  </section>
{/if}
