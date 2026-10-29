<script lang="ts">
  import IconButton from '../base/IconButton.svelte';
  import { t } from '../i18n/index.svelte';
  import { openTabPopout } from './tab-popout';
  import { sidebarTabs } from './tab-store.svelte';
  import { tabRegistry } from './registry';
  import type { DynamicTabDef } from './types';
  import ZoneShell from '../zone-shell/ZoneShell.svelte';
  import type { TabRef } from '../zone-shell/zone-types';
  import { rootZone, SESSION_LIST_TAB } from '../drawer-layout/root-zone.svelte';

  const zone = rootZone();
  const dynamicOnly = (tab: TabRef): boolean => tab.key !== SESSION_LIST_TAB;
  const active = $derived(sidebarTabs.active());

  const defOf = (tab: TabRef): DynamicTabDef | undefined => tabRegistry.get(tab.key) ?? undefined;

  function bodyOf(def: DynamicTabDef) {
    return def.body as { component: import('svelte').Component; titleKey?: string; titleActions?: import('svelte').Component<{ popout?: boolean }> };
  }
</script>

{#snippet dynamicTab(one: TabRef)}
  {@const def = defOf(one)}
  {#if def}
    {@const body = bodyOf(def)}
    <section class="dtb" data-tab-body={def.id} hidden={active !== def.id} aria-label={t(def.labelKey, { count: 0 })}>
      {#if body.titleKey}
        <header class="dtb-title">
          <h2 class="dtb-title-text">{t(body.titleKey)}</h2>
          <span class="dtb-title-actions">
            {#if body.titleActions}<body.titleActions />{/if}
            {#if def.popout}
              <IconButton label={t('drawer.tabs.pop_out', { name: t(def.labelKey, { count: 0 }) })} variant="quiet" icon="external"
                data-tab-popout={def.id} onclick={() => openTabPopout(def.id, window, def.popoutParams?.(), def.popoutMulti === true)} />
            {/if}
          </span>
        </header>
      {/if}
      <div class="dtb-content"><body.component /></div>
    </section>
  {/if}
{/snippet}

<ZoneShell {zone} tab={dynamicTab} only={dynamicOnly} fold />

<style>
  @layer components {
    .dtb {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-height: 0;
    }

    .dtb[hidden] {
      display: none;
    }

    .dtb-title {
      display: flex;
      align-items: center;
      min-height: var(--oc-titlerow-h, 37px);
      padding: 0 var(--oc-space-3);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
    }

    .dtb-title-actions {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      margin-left: auto;
    }

    .dtb-title-actions :global([data-tab-popout]) {
      --oc-ibtn-size: 22px;
    }

    .dtb-title-text {
      margin: 0;
      font-size: var(--oc-fs-title, var(--oc-fs-body));
      font-weight: 400;
      letter-spacing: var(--oc-tracking-title, 0.8px);
      text-transform: uppercase;
      color: var(--oc-orange);
    }

    .dtb-content {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
    }
  }
</style>
