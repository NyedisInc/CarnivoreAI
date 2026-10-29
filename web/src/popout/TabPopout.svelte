<script lang="ts">
  /* pop-out window */
  import { onMount, untrack } from 'svelte';
  import { auth, initAuth, startEvents } from '../opscenter/api';
  import { t } from '../lib/i18n/index.svelte';
  import { popoutTab } from '../lib/dynamic-tabs/popout-tabs';
  import WidgetHead from '../opscenter/shell/WidgetHead.svelte';
  import { createFrameHeader } from '../opscenter/shell/frame-header.svelte';

  let { tab }: { tab: string } = $props();

  const def = $derived(popoutTab(tab));
  const body = $derived(def && 'component' in def.body
    ? (def.body as { component: import('svelte').Component<{ popout?: boolean }>; titleKey?: string; titleActions?: import('svelte').Component<{ popout?: boolean }> })
    : null);

  const header = untrack(() => createFrameHeader(`popout-tab:${tab}`));
  $effect.pre(() => {
    header.action = body?.titleActions ? actions : null;
  });

  onMount(() => {
    initAuth();
    startEvents();
  });
</script>

{#snippet actions()}
  {#if body?.titleActions}<body.titleActions popout={true} />{/if}
{/snippet}

{#if auth.state === 'signed-out'}
  <p class="tp-notice" role="status">{t('opscenter.popout.signed_out')}</p>
{:else if !def || !body}
  <p class="tp-notice" role="status" data-tab-unavailable>{t('opscenter.popout.tab_unavailable', { id: tab })}</p>
{:else}
  <section class="tp" data-popout-tab={def.id} aria-label={t(def.labelKey, { count: 0 })}>
    {#if body.titleKey}<WidgetHead {header} title={t(body.titleKey)} corner={null} onClose={null} withRight={false} />{/if}
    <div class="tp-body"><body.component popout={true} /></div>
  </section>
{/if}

<style>
  @layer components {
    .tp {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-width: 0;
      background: var(--oc-ground-panel);
      container: oc-head / inline-size;
    }

    .tp-body {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
    }

    .tp-notice {
      margin: var(--oc-space-4);
      color: var(--oc-text-muted);
      font: var(--oc-fs-label) var(--font-mono);
      letter-spacing: 0.08em;
    }
  }
</style>
