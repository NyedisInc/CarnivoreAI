
<script lang="ts">
    import { untrack } from 'svelte';
    import { Switch } from '../base';
    import { useRender } from './context';
    import { useForm } from './form-context';
    import { resolve, type UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'toggle' }> } = $props();
    const ctx = useRender();
    const form = useForm();
    const boundInitial = $derived(node.checked !== undefined ? Boolean(resolve(node.checked, ctx.data)) : false);
    let checked = $state(untrack(() => boundInitial));
    let dirty = $state(false);

    $effect(() => {
        const next = boundInitial;
        if (!dirty) {
            checked = next;
            form?.setField(node.name, next);
        }
    });

    $effect(() => {
        if (!form) return;
        return form.registerField(node.name, untrack(() => checked), () => null);
    });

    function getChecked(): boolean {
        return checked;
    }

    function setChecked(next: boolean): void {
        checked = next;
        dirty = true;
        form?.setField(node.name, next);
    }
</script>

<div class="cu-control cu-toggle" data-cu="toggle" data-name={node.name} data-tone={node.tone ?? 'normal'}>
    <Switch
        label={node.label}
        disabled={node.disabled}
        data-tone={node.tone ?? 'normal'}
        bind:checked={getChecked, setChecked}
    />
</div>
