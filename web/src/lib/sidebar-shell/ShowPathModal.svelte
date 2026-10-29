
<script lang="ts">
    import { onDestroy } from 'svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import IconButton from '../base/IconButton.svelte';
    import { t } from '../i18n/index.svelte';
    import { copyText } from '../settings-page/mcp-panel/api';

    interface Props {
        path: string;
        name: string;
        close: (value: null) => void;
    }

    let { path, name, close }: Props = $props();

    const RESULT_MS = 1500;

    let state = $state<'idle' | 'copied' | 'failed'>('idle');
    let timer: ReturnType<typeof setTimeout> | null = null;

    onDestroy(() => {
        if (timer !== null) clearTimeout(timer);
    });

    async function copy(): Promise<void> {
        try {
            await copyText(path);
            state = 'copied';
        } catch {
            state = 'failed';
        }
        if (timer !== null) clearTimeout(timer);
        timer = setTimeout(() => (state = 'idle'), RESULT_MS);
    }
</script>

<ModalShell title={t('sidebar.show_path.title', { name })} overlayClass="text-prompt-modal" onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {t('sidebar.show_path.title', { name })}</span>
            <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close
                onclick={() => close(null)} />
        </div>
    {/snippet}
    <div class="sp-field" data-show-path-modal>
        <code class="sp-path" data-show-path-value>{path}</code>
        <button type="button" class="modal-btn modal-btn-secondary sp-copy" data-show-path-copy
            onclick={() => void copy()}
            >{state === 'copied' ? t('sidebar.show_path.copied') : state === 'failed' ? t('sidebar.show_path.copy_failed') : t('sidebar.show_path.copy')}</button>
    </div>
    {#snippet footer()}
        <button type="button" class="modal-btn modal-btn-secondary" data-show-path-close
            onclick={() => close(null)}>{t('modal.close')}</button>
    {/snippet}
</ModalShell>

<style>
  @layer components {
      .sp-field {
          display: flex;
          align-items: center;
          gap: var(--oc-space-2);
          min-width: 0;
          padding: var(--oc-space-1) var(--oc-space-1) var(--oc-space-1) var(--oc-space-3);
          border: 1px solid var(--oc-control-line);
          border-radius: var(--oc-radius-sm);
          background: var(--oc-ground-field);
      }

      .sp-path {
          flex: 1 1 auto;
          min-width: 0;
          padding: var(--oc-space-1) 0;
          font-family: var(--oc-font);
          font-size: var(--oc-fs-body);
          color: var(--oc-text-primary);
          overflow-wrap: anywhere;
          user-select: all;
      }

      .sp-copy {
          flex: none;
      }
  }
</style>
