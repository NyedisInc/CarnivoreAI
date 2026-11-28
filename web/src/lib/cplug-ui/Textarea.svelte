
<script lang="ts">
    import { untrack } from 'svelte';
    import { Field } from '../base';
    import { useRender } from './context';
    import { useForm } from './form-context';
    import { resolve, type UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'textarea' }> } = $props();
    const ctx = useRender();
    const form = useForm();
    const boundInitial = $derived(String(resolve(node.value ?? '', ctx.data)));
    let value = $state(untrack(() => boundInitial));
    let dirty = $state(false);
    let error = $state<string | null>(null);

    $effect(() => {
        const next = boundInitial;
        if (!dirty) {
            value = next;
            form?.setField(node.name, next);
        }
    });

    function validate(): string | null {
        if (node.required && !node.disabled && value.trim() === '') {
            error = ctx.t('cplug_ui.field_required');
            return error;
        }
        error = null;
        return null;
    }

    $effect(() => {
        if (!form) return;
        return form.registerField(node.name, untrack(() => value), validate);
    });

    function getValue(): string {
        return value;
    }

    function setValue(next: string): void {
        value = next;
        dirty = true;
        error = null;
        form?.setField(node.name, next);
    }
</script>

<div class="cu-control" data-cu="textarea" data-name={node.name}>
    <Field
        multiline
        rows={node.rows ?? 3}
        label={node.label}
        name={node.name}
        placeholder={node.placeholder}
        required={node.required}
        disabled={node.disabled}
        error={error ?? undefined}
        bind:value={getValue, setValue}
    />
</div>
