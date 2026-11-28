
<script lang="ts">
    import { Button, Field, Select } from '../base';
    import type { SelectChoice } from '../base/Select.svelte';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import { t } from '../i18n/index.svelte';

    export interface NewGroupAnswer {
        name: string;
        parentKey: string | null;
    }

    interface Props {
        initialParent: string;
        choices: readonly SelectChoice[];
        close: (value: NewGroupAnswer | null) => void;
    }

    const { initialParent, choices, close }: Props = $props();
    let name = $state('');
    // svelte-ignore state_referenced_locally
    let location = $state(initialParent);
    let nameEl = $state<HTMLInputElement | HTMLTextAreaElement | null>(null);

    $effect(() => {
        const el = nameEl;
        if (el) queueMicrotask(() => el.focus());
    });

    function submit(): void {
        close({ name, parentKey: location || null });
    }

    function onKeydown(event: KeyboardEvent): void {
        if (event.key !== 'Enter' || event.isComposing) return;
        event.preventDefault();
        submit();
    }
</script>

<ModalShell look="titlerow" closable={false} title={t('sidebar.group.new.title')} onCancel={() => close(null)}>
    <div class="new-group-modal__fields">
        <Field
            label={t('sidebar.group.new.label')}
            placeholder={t('sidebar.group.new.placeholder')}
            autocomplete="off"
            spellcheck={false}
            bind:value={name}
            bind:element={nameEl}
            onkeydown={onKeydown}
            data-new-group-name=""
        />
        <Select
            label={t('sidebar.group.new.location')}
            options={choices}
            bind:value={location}
            data-new-group-location=""
        />
    </div>
    {#snippet footer()}
        <Button data-new-group-cancel onclick={() => close(null)}>{t('sidebar.group.new.cancel')}</Button>
        <Button variant="confirm" data-new-group-confirm onclick={submit}>{t('sidebar.group.new.create')}</Button>
    {/snippet}
</ModalShell>

<style>
    @layer components {
        .new-group-modal__fields {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
        }
    }
</style>
