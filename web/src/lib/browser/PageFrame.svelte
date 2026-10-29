<script lang="ts">
  /* frame, and the */
  import { untrack } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { frameable } from './page-frame';

  let { page }: { page: { key: string; src: string | null; frame: 'sandboxed' | 'app'; title: string } } = $props();

  const framed = untrack(() => frameable(page));
  const title = untrack(() => page.title);
</script>

{#if framed?.frame === 'sandboxed'}
  <iframe
    class="pf-frame pf-frame--sandboxed"
    sandbox="allow-scripts"
    referrerpolicy="no-referrer"
    src={framed.src}
    {title}
    data-page-frame="sandboxed"
  ></iframe>
{:else if framed?.frame === 'app'}
  <iframe
    class="pf-frame"
    sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads"
    referrerpolicy="no-referrer"
    src={framed.src}
    {title}
    data-page-frame="app"
  ></iframe>
{:else}
  <p class="pf-note" role="status" data-page-frame-unavailable>{t('browser.page.unavailable')}</p>
{/if}

<style>
  @layer components {
    .pf-frame {
      display: block;
      width: 100%;
      height: 100%;
      border: 0;
      background: var(--oc-ground-page);
    }

    .pf-frame--sandboxed {
      color-scheme: light;
      background: Canvas;
    }

    .pf-note {
      margin: 0;
      padding: var(--oc-space-3, 12px);
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-body);
    }
  }
</style>
