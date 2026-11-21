<script lang="ts">
  /* the drawer closed */
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { closeTerminalComponents, openTerminalComponents, terminalComponentsOpen } from '../../opscenter/terminal-surface-host';
  import { t } from '../i18n/index.svelte';

  let { place = 'drawer' }: { place?: 'drawer' | 'rail' } = $props();

  let button = $state<HTMLElement | null>(null);

  function toggle(): void {
    if (terminalComponentsOpen()) closeTerminalComponents();
    else openTerminalComponents(button, 'below');
  }
</script>


<button type="button" data-btn="quiet" data-size="icon" data-add-widget={place} aria-haspopup="dialog"
  aria-label={t('opscenter.awe_s3.add_widget')} data-tooltip={t('opscenter.awe_s3.add_widget.tip')} bind:this={button}
  onclick={toggle}><Icon name="grid" size={15} /></button>

<style>
  @layer components {
    [data-add-widget] {
      flex: 0 0 auto;
    }

    [data-add-widget='drawer'] {
      --oc-ibtn-size: 28px;
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
    }

    [data-add-widget='drawer']:hover:not(:disabled) {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
    }

    :global(body:not(.ps-grid-surface)) [data-add-widget] {
      display: none;
    }

    @media (max-width: 1023px) {
      [data-add-widget='drawer'] {
        display: none;
      }
    }
  }
</style>
