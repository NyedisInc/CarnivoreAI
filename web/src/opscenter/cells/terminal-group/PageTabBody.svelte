<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { browsers } from '../../../lib/browser/api.svelte';
  import BrowserView from '../../../lib/browser/BrowserView.svelte';
  import PageFrame from '../../../lib/browser/PageFrame.svelte';
  import type { PageInfo } from '../../../lib/browser/page-frame';
  import { openPages, pageById } from '../../../lib/browser/pages.svelte';
  import FileScreen from '../../../lib/open-files/FileScreen.svelte';
  import { fileById, openFiles } from '../../../lib/open-files/api.svelte';
  import { pageTabState } from './page-tab-state.svelte';
  import { inputFocus } from '../../lib/input-focus.svelte';
  import { pageTabId } from '../../engine/page-tabs';

  let { browserId }: { browserId: string } = $props();

  const info = $derived(pageTabState(browserId));
  const file = $derived(fileById(browserId));

  let held = $state<{ id: string; page: PageInfo } | null>(null);
  let fresh = $state(false);

  onMount(() => {
    void Promise.allSettled([openPages.refresh(true), openFiles.refresh(true), browsers.refresh(true)]).then((reads) => {
      for (const read of reads) {
        if (read.status === 'rejected') console.warn('page tab: list refresh failed', read.reason);
      }
      fresh = true;
    });
  });

  $effect(() => {
    const page = pageById(browserId);
    if (fresh && page && held?.id !== browserId) held = { id: browserId, page: { ...page } };
  });

  const shown = $derived(held && held.id === browserId ? held.page : null);

  const owner = $derived(pageTabId(browserId));

  $effect(() => {
    const key = owner;
    return () => inputFocus.forget(key);
  });

  function dropFocus(event: FocusEvent): void {
    const next = event.relatedTarget;
    const host = event.currentTarget;
    if (next instanceof Node && host instanceof Node && host.contains(next)) return;
    inputFocus.release(owner);
  }
</script>

<div
  class="oc-pg"
  data-page-tab={browserId}
  onfocusincapture={() => inputFocus.claim(owner)}
  onfocusoutcapture={dropFocus}
>
  {#if info.kind === 'file' && file}
    <FileScreen {file} />
  {:else if info.kind === 'page' && shown}
    <PageFrame page={shown} />
  {:else if info.kind === 'browser'}
    {#key browserId}
      <BrowserView {browserId} compact />
    {/key}
  {:else if info.kind === 'gone'}
    <State inline title={t('opscenter.tabs.page_gone')} />
  {:else}
    <State kind="loading" inline title={t('browser.page.loading')} />
  {/if}
</div>

<style>
  @layer components {
    .oc-pg {
      position: relative;
      flex: 1 1 auto;
      width: 100%;
      min-width: 0;
      min-height: 0;
      background: var(--oc-ground-page);
      color: var(--oc-text-primary);
      font-family: var(--oc-font, var(--font-mono));
    }

  }
</style>
