
<script lang="ts">
    import Field from '../../base/Field.svelte';
    import { secretField } from '../../secret-field';
    import type { Translate } from '../../sessions/types';
    import type { MaskedSecret } from '../settings-doc.svelte';
    import { settingsDoc } from '../settings-doc.svelte';
    import type { SettingDef } from '../settings-registry';

    interface Props {
        def: SettingDef;
        t: Translate;
        inputId: string;
    }

    const { def, t, inputId }: Props = $props();

    const control = $derived(def.control);
    const secret = $derived(control.kind === 'secret');
    const configured = $derived.by(() => {
        if (control.kind !== 'secret') return false;
        const group = settingsDoc.summary?.[control.field.group] as Record<string, unknown> | undefined;
        return !!(group?.[control.field.key] as MaskedSecret | undefined)?.configured;
    });
    const placeholder = $derived(
        control.kind === 'text'
            ? control.placeholder
            : t(configured ? 'settings.secret.placeholder_set' : 'settings.secret.placeholder_unset'),
    );
    const value = $derived(String(settingsDoc.value(def.id) ?? ''));
</script>

<Field
    id={inputId}
    block
    autocomplete="off"
    spellcheck={false}
    {placeholder}
    {value}
    oninput={(event) => settingsDoc.setDraft(def.id, (event.currentTarget as HTMLInputElement).value)}
    {@attach (node) => secretField(node as HTMLInputElement, secret)}
/>
{#if secret}
    <span class="sf__default">{t(configured ? 'settings.secret.state_set' : 'settings.secret.state_unset')}</span>
{/if}
