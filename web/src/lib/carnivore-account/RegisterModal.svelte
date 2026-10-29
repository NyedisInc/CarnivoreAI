
<script lang="ts">
    import { onMount } from 'svelte';
    import RegisterDialog from '../catalog/RegisterDialog.svelte';
    import { browserPublishHost, type PublishAccount } from '../catalog/publish';
    import { t } from '../i18n/index.svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import { Button } from '../base';

    interface Props {
        close: (value: 'registered' | null) => void;
    }

    const { close }: Props = $props();
    const host = browserPublishHost();
    let account = $state<PublishAccount | null>(null);
    let failure = $state<string | null>(null);

    onMount(async () => {
        try {
            account = await host.account();
        } catch {
            failure = t('account.refusal.register_failed');
        }
    });
</script>

<ModalShell title={t('account.refusal.register_title')} onCancel={() => close(null)}>
    <p>{t('account.refusal.register_lead')}</p>
    <RegisterDialog {account} {failure} {host} {t} onregistered={() => close('registered')} />
    {#snippet footer()}
        <Button onclick={() => close(null)}>
            {t('community.close')}
        </Button>
    {/snippet}
</ModalShell>
