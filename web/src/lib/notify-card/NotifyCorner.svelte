
<script lang="ts">
    import NotifyCard from './NotifyCard.svelte';
    import type { NotifyKind } from './contract.gen';
    import type { NotifyActs, NotifyCardData } from './types';

    interface Shown { kind: NotifyKind; card: NotifyCardData | null; acts?: NotifyActs; body?: string; mediaUrl?: string }
    interface Bridge { onCard(fn: (shown: Shown) => void): void; press(id: string): void; close(): void }

    const bridge = (globalThis as { CarnivoreCorner?: Bridge }).CarnivoreCorner;
    let shown: Shown = $state({ kind: 'notice', card: null });
    let answered: string | undefined = $state();
    bridge?.onCard((next) => {
        answered = undefined;
        shown = next;
    });
</script>

<NotifyCard {...shown} {answered} typing={false} onact={(id) => bridge?.press(id)} onclose={() => bridge?.close()} />
