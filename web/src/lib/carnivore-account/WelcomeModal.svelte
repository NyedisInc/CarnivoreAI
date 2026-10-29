<script lang="ts">
    import ModalShell from '../launchpad/ModalShell.svelte';
    import { t } from '../i18n/index.svelte';

    interface Props {
        close: (value: 'signin' | 'later') => void;
    }

    const { close }: Props = $props();
</script>

<ModalShell title={t('account.welcome.title')} onCancel={() => close('later')}>
    <ul class="welcome" data-welcome-modal>
        <li>{t('account.welcome.share')}</li>
        <li>{t('account.welcome.mobile')}</li>
        <li>{t('account.welcome.skills')}</li>
    </ul>

    {#snippet footer()}
        <button type="button" class="modal-btn modal-btn-secondary" onclick={() => close('later')} data-welcome-later>
            {t('account.welcome.later')}
        </button>
        <button type="button" class="modal-btn modal-btn-confirm" onclick={() => close('signin')} data-welcome-signin>
            {t('account.welcome.signin')}
        </button>
    {/snippet}
</ModalShell>

<style>
  @layer components {
    .welcome {
        margin: 0;
        padding: 0;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: 6px;
        color: var(--oc-text-secondary);
        font-size: 12px;
        line-height: 1.5;
    }

    .welcome li {
        padding-left: 8px;
        border-left: 2px solid var(--oc-orange);
    }
  }
</style>
