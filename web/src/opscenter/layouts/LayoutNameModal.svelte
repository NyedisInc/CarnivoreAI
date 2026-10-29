
<script lang="ts">
    import { onMount } from 'svelte';
    import ModalShell from '../../lib/launchpad/ModalShell.svelte';
    import { t } from '../../lib/i18n/index.svelte';
    import { NAME_MAX, nameProblem } from './shape';

    interface Props {
        suggested: string;
        save: (name: string) => Promise<string>;
        watchAbort: (cancel: () => void) => () => void;
        close: (value: boolean | null) => void;
    }

    let { suggested, save, watchAbort, close }: Props = $props();

    // svelte-ignore state_referenced_locally
    let name = $state(suggested);
    let error = $state('');
    let busy = $state(false);
    let field: HTMLInputElement | null = $state(null);

    onMount(() => watchAbort(() => close(false)));

    $effect(() => {
        const timer = setTimeout(() => {
            field?.focus();
            field?.select();
        }, 100);
        return () => clearTimeout(timer);
    });

    function localProblem(value: string): string {
        const problem = nameProblem(value);
        if (problem === 'empty') return t('layout.error.name_empty');
        if (problem === 'too_long') return t('layout.error.name_too_long', { max: NAME_MAX });
        if (problem === 'invalid') return t('layout.error.name_invalid');
        return '';
    }

    async function submit(): Promise<void> {
        if (busy) return;
        const refused = localProblem(name);
        if (refused) {
            error = refused;
            field?.focus();
            return;
        }
        busy = true;
        error = '';
        const answer = await save(name.trim());
        busy = false;
        if (!answer) {
            close(true);
            return;
        }
        error = answer;
        field?.focus();
    }

    function onKey(event: KeyboardEvent): void {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        void submit();
    }
</script>

<ModalShell
    title={t('layout.name.title')}
    overlayClass="text-prompt-modal"
    dismissable={!busy}
    onCancel={() => close(false)}
>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {t('layout.name.title')}</span>
            <button type="button" class="modal-close" aria-label={t('modal.close')}
                disabled={busy} onclick={() => close(false)}>&times;</button>
        </div>
    {/snippet}
    <div class="modal-input-group" data-layout-name-modal>
        <label class="modal-label" for="layout-name-input">{t('layout.name.label')}</label>
        <input
            type="text"
            class="modal-input"
            id="layout-name-input"
            autocomplete="off"
            spellcheck="false"
            maxlength={NAME_MAX * 2}
            placeholder={t('layout.name.placeholder')}
            aria-invalid={error ? 'true' : undefined}
            aria-describedby={error ? 'layout-name-error' : 'layout-name-hint'}
            bind:this={field}
            bind:value={name}
            onkeydown={onKey}
        />
        <p class="lnm-hint" id="layout-name-hint">{t('layout.name.hint')}</p>
        {#if error}
            <p class="lnm-error" id="layout-name-error" role="alert">{error}</p>
        {/if}
    </div>
    {#snippet footer()}
        <button class="modal-btn modal-btn-secondary" id="layout-name-cancel" disabled={busy} onclick={() => close(false)}
            >{t('layout.name.cancel')}</button
        >
        <button class="modal-btn modal-btn-confirm" id="layout-name-save" disabled={busy} onclick={() => void submit()}
            >{busy ? t('layout.name.saving') : t('layout.name.save')}</button
        >
    {/snippet}
</ModalShell>

<style>
  @layer components {
      .lnm-hint {
          margin: 6px 0 0;
          font-size: var(--oc-fs-micro, var(--oc-fs-micro));
          color: var(--oc-text-muted);
          line-height: 1.45;
      }

      .lnm-error {
          margin: var(--oc-space-2) 0 0;
          padding: 6px var(--oc-space-2);
          border-left: 2px solid var(--oc-coral);
          background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-raised));
          color: var(--oc-text-primary);
          font-size: var(--oc-fs-body);
          line-height: 1.45;
      }
  }
</style>
