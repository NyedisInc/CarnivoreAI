
<script lang="ts">
    import { onMount } from 'svelte';
    import { asleep, recent } from '../api';
    import { rowIdOfSlot } from '../engine/slot-identity';
    import { memberForRow } from './mode.svelte';
    import MemberDownRow from './MemberDownRow.svelte';

    let { instance }: { instance: string } = $props();

    const rowId = $derived(rowIdOfSlot(instance));
    const member = $derived(memberForRow(rowId));

    onMount(() => {
        void asleep.refresh(true);
        void recent.refresh(true);
    });
</script>

<MemberDownRow {member} {instance} />
