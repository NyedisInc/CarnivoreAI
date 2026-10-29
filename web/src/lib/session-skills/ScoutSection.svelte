<script lang="ts">
  import { onMount } from 'svelte';
  import { Button } from '../base';
  import { t } from '../i18n/index.svelte';
  import { openModal, openModalCount } from '../modal';
  import { browserCatalogHost } from '../catalog/catalog';
  import { cardView } from '../catalog/card';
  import { quickAdd } from '../catalog/quick-add';
  import InstallSheet from '../catalog/InstallSheet.svelte';
  import { refusalMessage } from '../../../../client/js/labels/skill.js';
  import type { SheetOutcome } from '../catalog/types';
  import { fetchScout, requestScout, scoutRefusal, type ScoutReply } from './scout';

  let { sessionId, workingDir }: { sessionId: string; workingDir: string | null } = $props();

  const POLL_MS = 4000;
  const POLL_MAX = 30;

  let reply = $state<ScoutReply | null>(null);
  let asking = $state(false);
  let error = $state<string | null>(null);
  let installing = $state<string | null>(null);
  let done = $state<string[]>([]);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let live = true;
  let gaveUp = $state(false);
  const stillWaiting = $derived(reply?.state === 'waiting' && !gaveUp);

  async function read(tries: number): Promise<void> {
    try {
      reply = await fetchScout(sessionId);
    } catch {
      return;
    }
    if (reply.state !== 'waiting') return;
    if (!live) return;
    if (tries < POLL_MAX) timer = setTimeout(() => void read(tries + 1), POLL_MS);
    else gaveUp = true;
  }

  onMount(() => {
    void read(0);
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  });

  async function scout(): Promise<void> {
    if (asking) return;
    asking = true;
    error = null;
    try {
      await requestScout(sessionId);
      reply = { state: 'waiting', suggestions: [] };
      gaveUp = false;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void read(0), POLL_MS);
    } catch (err: unknown) {
      error = t('skills.scout.failed', { reason: scoutRefusal(err, t('skills.scout.unreachable')) });
    } finally {
      asking = false;
    }
  }

  async function install(itemId: string, name: string): Promise<void> {
    if (installing || openModalCount() > 0) return;
    installing = itemId;
    error = null;
    try {
      const host = browserCatalogHost();
      const outcome = await quickAdd(host, itemId, 'project', workingDir);
      if (outcome.outcome === 'installed') {
        done = [...done, itemId];
      } else if (outcome.outcome === 'sheet') {
        const item = await host.item(itemId);
        if (!item) throw new Error(t('skills.scout.unreachable'));
        const answer = (await openModal(InstallSheet as never, {
          card: cardView(item, false),
          host,
          t,
          prefill: outcome.prefill,
        } as never)) as SheetOutcome | null;
        if (answer && answer.outcome === 'installed') done = [...done, itemId];
      } else {
        error = t('skills.scout.install_failed', { name, reason: refusalMessage(outcome.code, t) });
      }
    } catch (err: unknown) {
      error = t('skills.scout.install_failed', { name, reason: err instanceof Error ? err.message : '' });
    } finally {
      installing = null;
    }
  }
</script>

<h3 class="sal-section">{t('skills.scout.title')}</h3>
<div class="sal-scout" data-skill-scout>
  <Button size="sm" data-scout-button disabled={asking || stillWaiting} onclick={() => void scout()}>
    {asking || stillWaiting ? t('skills.scout.asking') : t('skills.scout.button')}
  </Button>
  <span class="sal-note sal-scout-hint">{t('skills.scout.hint')}</span>
</div>
{#if error}<p class="sal-error" role="alert" data-scout-error>{error}</p>{/if}
{#if reply?.state === 'ready'}
  {#if reply.suggestions.length === 0}
    <p class="sal-note" data-scout-empty>{t('skills.scout.empty')}</p>
  {:else}
    <ul class="sal-chips" data-scout-chips>
      {#each reply.suggestions as s (s.item_id)}
        <li class="sal-chip-row" data-scout-chip={s.item_id}>
          <Button
            size="sm"
            data-scout-install={s.item_id}
            disabled={installing !== null || done.includes(s.item_id)}
            onclick={() => void install(s.item_id, s.name)}
          >{done.includes(s.item_id) ? t('skills.scout.installed', { name: s.name }) : installing === s.item_id ? t('skills.scout.installing') : t('skills.scout.install', { name: s.name })}</Button>
          <span class="sal-chip-why">{s.reason}</span>
        </li>
      {/each}
    </ul>
  {/if}
{/if}
