
<script lang="ts">
    import { useRender } from './context';
    import { resolve, type UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'table' }> } = $props();
    const ctx = useRender();
</script>

<div class="cu-table-wrap" data-cu="table">
    <table class="cu-table">
        <thead><tr>{#each node.columns as column}<th>{column}</th>{/each}</tr></thead>
        <tbody>
            {#each node.rows as row}<tr>{#each row as cell}<td>{resolve(cell, ctx.data)}</td>{/each}</tr>{:else}<tr><td colspan={node.columns.length} class="cu-table__empty">{ctx.t('cplug_ui.table_empty')}</td></tr>{/each}
        </tbody>
    </table>
</div>
