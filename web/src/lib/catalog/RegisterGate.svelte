
<script lang="ts">
    import ModalShell from '../launchpad/ModalShell.svelte';
    import type { Translate } from '../sessions/types';
    import type { PublishHost } from './publish';
    import RegisterDialog from './RegisterDialog.svelte';
    import type { RegisterGate } from './register-gate.svelte';

    interface Props {
        gate: RegisterGate;
        host: PublishHost;
        t: Translate;
    }

    const { gate, host, t }: Props = $props();
</script>

{#if gate.open}
    <ModalShell title={t('community.gate.title')} onCancel={() => gate.dismiss()}>
        <p class="gate__lead">{t('community.gate.needed')}</p>
        <RegisterDialog
            account={gate.account}
            failure={gate.failure}
            {host}
            {t}
            onregistered={() => gate.registered()}
        />
        {#snippet footer()}
            <button type="button" class="modal-btn modal-btn-secondary" id="catalog-gate-close" onclick={() => gate.dismiss()}>
                {t('community.close')}
            </button>
        {/snippet}
    </ModalShell>
{/if}

<style>
  @layer components {
    .gate__lead {
        margin: 0 0 8px;
        color: var(--oc-text-primary);
        font-size: 12px;
        line-height: 1.5;
    }
  }
</style>
