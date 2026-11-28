
<script lang="ts">
    import { untrack } from 'svelte';
    import { Select, type SelectOption } from '../base';
    import { useRender } from './context';
    import { useForm } from './form-context';
    import { resolve, type UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'select' }> } = $props();
    const ctx = useRender();
    const form = useForm();
    const options = $derived<SelectOption[]>(
        node.options.map((opt) => (typeof opt === 'string' ? { value: opt, label: opt } : { value: opt.value, label: opt.label })),
    );
    const boundInitial = $derived.by(() => {
        if (node.value === undefined) return options[0]?.value ?? '';
        const resolved = String(resolve(node.value, ctx.data));
        if (resolved === '' && !options.some((opt) => opt.value === '')) return options[0]?.value ?? '';
        return resolved;
    });

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
        if (node.required && !node.disabled && value === '') {
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

<div class="cu-control" data-cu="select" data-name={node.name}>
    <Select
        label={node.label}
        name={node.name}
        {options}
        required={node.required}
        disabled={node.disabled}
        error={error ?? undefined}
        bind:value={getValue, setValue}
    />
</div>
