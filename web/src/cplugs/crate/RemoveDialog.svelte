
<script lang="ts">
    import { t as reactiveT, type Translate } from '../sdk';
    import { Button, Checkbox, IconButton, ModalShell } from '../sdk/ui';
    import { errorSentence, type Fetcher } from './crate-api';
    import { removeCrate, type RemoveTarget } from './folder-crates-api';
    import './crate-dialog.css';

    interface Props {
        target: RemoveTarget;
        name: string;
        recorded?: boolean;
        otherCopy?: boolean;
        close: (value: boolean | null) => void;
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { target, name, recorded = false, otherCopy = false, close, t = reactiveT, fetcher }: Props = $props();

    let alsoSecond = $state(false);
    let busy = $state(false);
    let problem = $state('');

    async function go(): Promise<void> {
        busy = true;
        problem = '';
        try {
            await removeCrate(target, otherCopy && alsoSecond, fetcher);
            close(true);
        } catch (error) {
            problem = errorSentence(error, t);
            busy = false;
        }
    }
</script>

<ModalShell title={t('cplug.crate.remove.title', { subject: name })} overlayClass="text-prompt-modal crt-modal" dismissable={!busy} onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">{t('cplug.crate.remove.title', { subject: name })}</span>
            <IconButton label={t('modal.close')} icon="close" variant="close" iconSize={14} onclick={() => close(null)} />
        </div>
    {/snippet}
    <p class="modal-description" data-crt-remove-body>{t('cplug.crate.remove.body', { name })}</p>
    {#if recorded}<p class="tm__sub" data-crt-remove-recorded>{t('cplug.crate.remove.recorded')}</p>{/if}
    {#if otherCopy}
        <Checkbox label={t('cplug.crate.remove.also_second')} hint={t('cplug.crate.remove.also_second_hint')}
            bind:checked={alsoSecond} disabled={busy} data-crt-remove-second="" />
    {/if}
    {#if problem}<p class="tm__problem" role="alert" data-crt-problem>{problem}</p>{/if}
    {#snippet footer()}
        <Button variant="secondary" disabled={busy} onclick={() => close(null)}>{t('cplug.crate.remove.cancel')}</Button>
        <Button variant="danger" data-crt-remove-go disabled={busy} onclick={() => void go()}>
            {t(busy ? 'cplug.crate.remove.going' : 'cplug.crate.remove.go')}
        </Button>
    {/snippet}
</ModalShell>
