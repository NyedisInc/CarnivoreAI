
<script lang="ts">
    import Button from '../base/Button.svelte';
    import IconButton from '../base/IconButton.svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import type { Translate } from '../sessions/types';
    import './plugin-pane.css';

    interface Props {
        t: Translate;
        close: (value: boolean | null) => void;
    }

    const { t, close }: Props = $props();
</script>

<ModalShell title={t('plugins.page.sideload.confirm.label')} overlayClass="text-prompt-modal na-flow" onCancel={() => close(null)} data-sideload-confirm="">
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">{t('plugins.page.sideload.confirm.label')}</span>
            <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close onclick={() => close(null)} />
        </div>
    {/snippet}
    <p class="plp-warn plp-danger" role="alert" data-sideload-risk>{t('plugins.page.sideload.warning.risk')}</p>
    {#snippet footer()}
        <Button size="sm" data-sideload-confirm-cancel="" onclick={() => close(null)}>{t('plugins.page.sideload.cancel')}</Button>
        <Button size="sm" variant="danger" data-sideload-confirm-go="" onclick={() => close(true)}>{t('plugins.page.sideload.confirm.go')}</Button>
    {/snippet}
</ModalShell>
