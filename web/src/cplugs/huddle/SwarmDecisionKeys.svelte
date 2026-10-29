<script lang="ts">
  import { t } from '../sdk';
  import { huddle, setApproved, reply } from './huddle.svelte';
  import type { HuddleItem } from './huddle-model';
  import { decisionKeys, decisionOf } from './chat/chat-model';

  let { item }: { item: HuddleItem } = $props();

  let busy = $state(false);
  let settled = $state<'yes' | 'no' | null>(null);
  let failure = $state('');
  const keys = $derived(decisionKeys(item));
  const decided = $derived(decisionOf(item));
  const open = $derived(!!keys && !decided && !settled);

  async function decide(yes: boolean): Promise<void> {
    if (busy || !keys) return;
    busy = true;
    failure = '';
    const ok = yes ? await setApproved(item, true) : await reply(item, t(keys.noText), [], false);
    if (ok) settled = yes ? 'yes' : 'no';
    else failure = huddle.notice || t('cplug.huddle.refused.failed');
    busy = false;
  }
</script>

{#if keys && (settled || decided)}
  <p class="hdk-decision" data-chat-decision={settled ?? decided}>{settled ? t((settled === 'yes' ? keys.yes : keys.no) ?? keys.no) : t(`cplug.huddle.chat.decided.${decided}`)}</p>
{/if}
{#if keys && open}
  <div class="hdk-actions" data-chat-receipt>
    <div class="hdk-keys">
      <button type="button" class="oc-btn oc-btn--sm" disabled={busy} data-decide="no" onclick={() => decide(false)}>{t(keys.no)}</button>
      {#if keys.yes}<button type="button" class="oc-btn oc-btn--sm oc-btn--confirm" disabled={busy} data-decide="yes" onclick={() => decide(true)}>{t(keys.yes)}</button>{/if}
    </div>
    {#if failure}<p class="hdk-refusal" role="status" data-chat-refusal>{failure}</p>{/if}
  </div>
{/if}

<style>
  @layer components {
    .hdk-decision {
      margin: 0;
      padding-top: 8px;
      color: var(--oc-green-dim);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdk-actions {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding-top: 8px;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdk-refusal {
      margin: 0;
      color: var(--oc-coral);
      font-size: var(--oc-fs-micro);
    }

    .hdk-keys {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }
  }
</style>
