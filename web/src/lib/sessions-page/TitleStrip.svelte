
<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Translate } from '../sessions/types';
    import TitleActions from './TitleActions.svelte';
    import FleetSummary from './FleetSummary.svelte';
    import type { FleetCounts } from './filters';

    interface Props {
        title: string;
        onNewProject: () => void;
        onNewCompany: () => void;
        onNewSession: () => void;
        showHidden: boolean;
        onToggleHidden: () => void;
        showFold: boolean;
        allOpen: boolean;
        onToggleAll: () => void;
        find: Snippet;
        counts: FleetCounts;
        listingDown: boolean;
        historyFailed: boolean;
        t: Translate;
    }
    const { title, onNewProject, onNewCompany, onNewSession, showHidden, onToggleHidden, showFold, allOpen, onToggleAll, find, counts, listingDown, historyFailed, t }: Props = $props();
</script>

<div class="sp-strip">
    <div class="sp-tbl">
        <span class="pl-title" aria-hidden="true">{title}</span>
        <TitleActions {onNewProject} {onNewCompany} {onNewSession} {showHidden} {onToggleHidden} {showFold} {allOpen} {onToggleAll} {t} />
    </div>
    <div class="sp-find">{@render find()}</div>
    <FleetSummary {counts} {listingDown} {historyFailed} {t} />
</div>
