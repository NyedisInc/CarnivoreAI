<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { auth, initAuth, startEvents } from '../opscenter/api';
  import { t } from '../lib/i18n/index.svelte';
  import { popoutTab } from '../lib/dynamic-tabs/popout-tabs';
  import { cplugPopoutTabsOn } from '../plugins/host/readers';
  import { POPOUT_CPLUGS } from '../plugins/popout';
  import { enablementKnown } from '../plugins/host/popout-widgets';
  import { pluginTabOf, pluginTabs } from '../lib/cplug-ui/plugin-tabs.svelte';
  import { pluginsStore } from '../lib/plugins/store.svelte';
  import Tag from '../lib/base/Tag.svelte';
  import WidgetHead from '../opscenter/shell/WidgetHead.svelte';
  import { createFrameHeader } from '../opscenter/shell/frame-header.svelte';

  let { tab }: { tab: string } = $props();

  const compiledCandidate = $derived(POPOUT_CPLUGS.some((c) => c.tabs.some((item) => item.id === tab && item.popout === true)));
  const compiledEnabled = $derived(compiledCandidate ? (cplugPopoutTabsOn().find((item) => item.id === tab) ?? null) : null);
  const def = $derived(compiledCandidate ? compiledEnabled : popoutTab(tab));
  const pluginEntry = $derived(pluginTabOf(tab));
  const waiting = $derived(
    !def && (
      (compiledCandidate && !enablementKnown()) ||
      (tab.startsWith('cplug-') && !pluginTabs.loaded && pluginsStore.loading)
    )
  );
  const body = $derived(def && 'component' in def.body
    ? (def.body as { component: import('svelte').Component<{ popout?: boolean; tabId?: string }>; titleKey?: string; titleActions?: import('svelte').Component<{ popout?: boolean; tabId?: string }> })
    : null);

  const header = untrack(() => createFrameHeader(`popout-tab:${tab}`));
  $effect.pre(() => {
    header.action = body?.titleActions || pluginEntry ? actions : null;
  });

  onMount(() => {
    initAuth();
    startEvents();
  });
  $effect(() => {
    const title = body?.titleKey ? t(body.titleKey) : def ? t(def.labelKey, { count: 0 }) : '';
    if (title) document.title = title;
  });
</script>

{#snippet actions()}
  {#if pluginEntry}
    <Tag tone={pluginEntry.plugin.unverified ? 'warn' : 'accent'} data-cplug-mark data-unverified={pluginEntry.plugin.unverified ? '' : undefined}>{t(pluginEntry.plugin.unverified ? 'cplug_ui.mark.unverified' : 'cplug_ui.mark.third_party')}</Tag>
  {/if}
  {#if body?.titleActions}<body.titleActions popout={true} tabId={tab} />{/if}
{/snippet}

{#if auth.state === 'signed-out'}
  <p class="tp-notice" role="status">{t('opscenter.popout.signed_out')}</p>
{:else if waiting}
  <p class="tp-notice" role="status" data-tab-loading></p>
{:else if !def || !body}
  <p class="tp-notice" role="status" data-tab-unavailable>{t('opscenter.popout.tab_unavailable', { id: tab })}</p>
{:else}
  <section class="tp" data-popout-tab={def.id} aria-label={t(def.labelKey, { count: 0 })}>
    {#if body.titleKey}<WidgetHead {header} title={t(body.titleKey)} corner={null} onClose={null} withRight={false} />{/if}
    <div class="tp-body"><body.component popout={true} tabId={tab} /></div>
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
