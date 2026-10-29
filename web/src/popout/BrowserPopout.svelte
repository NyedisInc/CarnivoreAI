<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { auth, initAuth, startEvents } from '../opscenter/api';
  import { t } from '../lib/i18n/index.svelte';
  import { browserById } from '../lib/browser/api.svelte';
  import BrowserView from '../lib/browser/BrowserView.svelte';
  import WidgetHead from '../opscenter/shell/WidgetHead.svelte';
  import { createFrameHeader } from '../opscenter/shell/frame-header.svelte';

  let { browser }: { browser: string } = $props();

  const label = $derived(browserById(browser)?.label ?? '');
  const header = untrack(() => createFrameHeader(`popout-browser:${browser}`));

  onMount(() => {
    initAuth();
    startEvents();
  });

  $effect(() => {
    document.title = label ? t('browser.screen', { label }) : t('browser.page');
  });
</script>

{#if auth.state === 'signed-out'}
  <p class="bp-notice" role="status">{t('opscenter.popout.signed_out')}</p>
{:else}
  <section class="bp" data-popout-browser={browser} aria-label={t('browser.screen', { label: label || t('browser.page') })}>
    <WidgetHead {header} title={label || t('browser.page')} corner={null} onClose={null} withRight={false} />
    <div class="bp-body"><BrowserView browserId={browser} /></div>
  </section>
{/if}

<style>
  @layer components {
    .bp {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-width: 0;
      background: var(--oc-ground-panel);
      container: oc-head / inline-size;
    }

    .bp-body {
      flex: 1 1 auto;
      min-height: 0;
    }

    .bp-notice {
      margin: var(--oc-space-4);
      color: var(--oc-text-muted);
      font: var(--oc-fs-label) var(--font-mono);
      letter-spacing: 0.08em;
    }
  }
</style>
