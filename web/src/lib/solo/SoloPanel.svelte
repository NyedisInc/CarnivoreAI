<script lang="ts">
  import { Button } from '../base';
  import { t } from '../i18n/index.svelte';

  let { kind, name = '', sessionUuid = '', agentType = '' }: {
    kind: 'looking' | 'asleep' | 'gone' | 'ended';
    name?: string;
    sessionUuid?: string;
    agentType?: string;
  } = $props();

  let busy = $state(false);
  let note = $state('');

  function api(): { wakeSession(uuid: string, agent?: string): Promise<{ status?: string; detail?: string }>;
    recreateSession(uuid: string, agent: string): Promise<{ status?: string; detail?: string }> } | undefined {
    return (globalThis as { API?: ReturnType<typeof api> }).API;
  }

  async function act(): Promise<void> {
    const client = api();
    if (!client || !sessionUuid || busy) return;
    busy = true;
    note = '';
    try {
      const answer = kind === 'asleep'
        ? await client.wakeSession(sessionUuid)
        : await client.recreateSession(sessionUuid, agentType);
      if (answer && answer.status === 'refused') note = answer.detail ?? t('solo.failed');
    } catch (error) {
      note = error instanceof Error ? error.message : t('solo.failed');
    } finally {
      busy = false;
    }
  }

  function closeWindow(): void {
    globalThis.close();
  }
</script>

<section class="solo" role="status" data-solo-kind={kind}>
  <header class="solo__bar">
    <h1 class="solo__label">{t(`solo.${kind}.title`)}</h1>
    {#if name}<span class="solo__name">{name}</span>{/if}
  </header>
  <div class="solo__body">
    {#if kind === 'asleep'}
      <Button variant="confirm" disabled={busy || !sessionUuid} onclick={act}>{t('solo.asleep.wake')}</Button>
    {:else if kind === 'gone'}
      <Button variant="confirm" disabled={busy || !sessionUuid} onclick={act}>{t('solo.gone.reopen')}</Button>
    {:else if kind === 'ended'}
      <Button onclick={closeWindow}>{t('solo.ended.close')}</Button>
    {/if}
    {#if note}<p class="solo__note">{note}</p>{/if}
  </div>
</section>

<style>
  .solo {
    position: fixed;
    inset: 0;
    z-index: 40;
    display: flex;
    flex-direction: column;
    background: var(--oc-ground-page);
    color: var(--oc-text-primary);
    font-family: var(--font-mono);
  }

  .solo__bar {
    display: flex;
    align-items: center;
    gap: var(--oc-space-2);
    min-width: 0;
    min-height: var(--oc-titlerow-h, 37px);
    padding: 0 var(--oc-space-3);
    background: var(--oc-ground-titlerow);
    box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
  }

  .solo__label {
    margin: 0;
    font-size: var(--oc-fs-title, 12px);
    font-weight: 400;
    letter-spacing: var(--oc-tracking-title, 0.8px);
    text-transform: uppercase;
    color: var(--oc-orange);
    white-space: nowrap;
  }

  .solo__name {
    min-width: 0;
    font-size: var(--oc-fs-micro, 10px);
    color: var(--oc-text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .solo__body {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--oc-space-3);
    padding: var(--oc-space-4) var(--oc-space-3);
  }

  .solo__note {
    margin: 0;
    font-size: var(--oc-fs-micro, 10px);
    color: var(--oc-coral);
  }
</style>
