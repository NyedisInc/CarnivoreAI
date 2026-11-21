
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import { NEW_PROJECT_KEYS } from '../../../../client/js/labels/new-project.js';
    import type { Translate } from '../sessions/types';
    import type { SelectChoice } from '../base/Select.svelte';
    import Field from '../base/Field.svelte';
    import Select from '../base/Select.svelte';
    import Button from '../base/Button.svelte';

    interface Props {
        name: string;
        parent: string;
        folder: string;
        parentChoices: readonly SelectChoice[];
        help: string;
        error?: string;
        busy?: boolean;
        canCreate: boolean;
        oncreate: () => void;
        oncancel: () => void;
        t?: Translate;
    }

    let {
        name = $bindable(), parent = $bindable(), folder = $bindable(), parentChoices, help, error = '', busy = false,
        canCreate, oncreate, oncancel, t = reactiveT,
    }: Props = $props();
</script>

<div class="new-project-box" data-new-company>
    <div class="modal-label">{t(NEW_PROJECT_KEYS.newcoTitle)}</div>
    <Field label={t(NEW_PROJECT_KEYS.newcoName)} id="new-company-name" autocomplete="off" bind:value={name} />
    <Select label={t(NEW_PROJECT_KEYS.newcoParent)} id="new-company-parent" bind:value={parent} options={parentChoices} />
    <Field
        label={t(NEW_PROJECT_KEYS.newcoFolder)}
        id="new-company-folder"
        placeholder={t(NEW_PROJECT_KEYS.newcoFolderPlaceholder)}
        autocomplete="off"
        spellcheck="false"
        {help}
        {error}
        bind:value={folder}
    />
    <div class="new-project-box__buttons">
        <Button id="new-company-cancel" onclick={oncancel}>{t(NEW_PROJECT_KEYS.newcoCancel)}</Button>
        <Button variant="confirm" id="new-company-create" disabled={!canCreate || busy} onclick={oncreate}>{t(NEW_PROJECT_KEYS.newcoCreate)}</Button>
    </div>
</div>

<style>
    @layer components {
        .new-project-box {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
            min-width: 0;
            padding: var(--oc-space-3);
            border: var(--oc-border) solid var(--oc-line-hairline);
            background: var(--oc-ground-titlerow);
            box-shadow: inset var(--oc-space-1) 0 0 0 var(--oc-orange);
        }

        .new-project-box__buttons {
            display: flex;
            justify-content: flex-end;
            gap: var(--oc-space-2);
        }
    }
</style>
