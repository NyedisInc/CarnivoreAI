
<script lang="ts">
    import { onMount } from 'svelte';
    import Button from '../../lib/base/Button.svelte';
    import Field from '../../lib/base/Field.svelte';
    import IconButton from '../../lib/base/IconButton.svelte';
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
    const FIELD_ID = 'layout-name-input';
    const field = (): HTMLInputElement | null => document.getElementById(FIELD_ID) as HTMLInputElement | null;

    onMount(() => watchAbort(() => close(false)));

    $effect(() => {
        const timer = setTimeout(() => {
            field()?.focus();
            field()?.select();
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
            field()?.focus();
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
        field()?.focus();
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
            <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close
                disabled={busy} onclick={() => close(false)} />
        </div>
    {/snippet}
    <div class="modal-input-group" data-layout-name-modal>
        <Field
            id={FIELD_ID}
            label={t('layout.name.label')}
            bind:value={name}
            autocomplete="off"
            spellcheck="false"
            maxlength={NAME_MAX * 2}
            placeholder={t('layout.name.placeholder')}
            help={t('layout.name.hint')}
            {error}
            onkeydown={onKey}
        />
    </div>
    {#snippet footer()}
        <Button id="layout-name-cancel" disabled={busy} onclick={() => close(false)}>{t('layout.name.cancel')}</Button>
        <Button variant="confirm" id="layout-name-save" disabled={busy} onclick={() => void submit()}
            >{busy ? t('layout.name.saving') : t('layout.name.save')}</Button>
    {/snippet}
</ModalShell>
