<script lang="ts">
  import Icon from '../../opscenter/ui/Icon.svelte';
  import CascadeMenu from './CascadeMenu.svelte';
  import type { MenuNode } from './add-component-menu';
  import { newGroup, newSession, newTerminal, startNewProject } from '../../opscenter/api';
  import { newBrowser } from '../browser/screen-host';
  import { t } from '../i18n/index.svelte';
  import { newSessionKinds, type NewSessionKind } from './drawer-tabs';

  interface PinGlobal {
    closeAfterSwitch?: () => void;
  }

  let open = $state(false);
  let button = $state<HTMLElement | null>(null);

  function closeIfOverlay(): void {
    (globalThis as { SessionSidebarPin?: PinGlobal }).SessionSidebarPin?.closeAfterSwitch?.();
  }

  function chooseKind(kind: NewSessionKind): void {
    if (kind === 'agent') newSession(null);
    else if (kind === 'terminal') newTerminal();
    else void newBrowser();
  }

  function leaf(action: () => unknown, leave = true): () => void {
    return () => {
      action();
      if (leave) closeIfOverlay();
      open = false;
      button?.focus();
    };
  }

  const root = $derived<MenuNode[]>([
    ...newSessionKinds().map((kind) => ({
      id: kind,
      label: t(`drawer.new.${kind}`),
      run: leaf(() => chooseKind(kind)),
    })),
    { id: 'project', label: t('drawer.new.project'), sep: true, run: leaf(startNewProject) },
    { id: 'group', label: t('drawer.new.group'), run: leaf(newGroup, false) },
  ]);
</script>


<button type="button" data-btn="quiet" data-size="icon" data-action="new-session" aria-haspopup="menu" aria-expanded={open}
  aria-label={t('drawer.action.new_session')} bind:this={button} onclick={() => (open = !open)}><Icon name="plus" size={15} /></button>

{#if open}
  <CascadeMenu {root} anchor={button} label={t('drawer.new.menu')} onClose={() => (open = false)} />
{/if}

<style>
  @layer components {
    :global([data-btn][data-action='new-session']) {
      --oc-ibtn-size: 28px;
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
    }

    :global([data-btn][data-action='new-session']:hover:not(:disabled)),
    :global([data-btn][data-action='new-session'][aria-expanded='true']) {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
    }
  }
</style>
