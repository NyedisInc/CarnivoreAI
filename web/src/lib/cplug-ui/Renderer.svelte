
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { runAction } from './api';
    import { provide } from './context';
    import HostFrame from './HostFrame.svelte';
    import Node from './Node.svelte';
    import { validateDocument, type Action, type Declared } from './validate';

    interface Props {
        cplugId: string;
        name: string;
        unverified?: boolean;
        document: unknown;
        declared: Declared;
        stale?: boolean;
        t: Translate;
        run?: (action: Action) => Promise<void>;
    }

    // svelte-ignore state_referenced_locally
    const { cplugId, name, unverified = false, document: raw, declared, stale = false, t, run = (action) => runAction(cplugId, action) }: Props = $props();

    const verdict = $derived(validateDocument(raw, declared));
    provide({ get data() { return verdict.ok ? verdict.doc.data : undefined; }, t, run: (action) => run(action) });
</script>

<HostFrame {name} {unverified} {t} note={!verdict.ok ? t('cplug_ui.could_not_draw') : stale ? t('cplug_ui.stale') : null}>
    {#if verdict.ok}<div class="cu-root" data-cu-root><Node node={verdict.doc.root} /></div>{/if}
</HostFrame>
