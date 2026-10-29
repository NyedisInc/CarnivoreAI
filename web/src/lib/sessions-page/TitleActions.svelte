
<script lang="ts">
    import IconButton from '../base/IconButton.svelte';
    import type { Translate } from '../sessions/types';

    interface Props {
        onNewProject: () => void;
        onNewCompany: () => void;
        onNewSession: () => void;
        showHidden: boolean;
        onToggleHidden: () => void;
        showFold: boolean;
        allOpen: boolean;
        onToggleAll: () => void;
        t: Translate;
    }
    const { onNewProject, onNewCompany, onNewSession, showHidden, onToggleHidden, showFold, allOpen, onToggleAll, t }: Props = $props();
    const foldName = $derived(t(allOpen ? 'sessions.page.fold.collapse_all' : 'sessions.page.fold.expand_all'));
    const projectName = $derived(t('sessions.page.act.new_project'));
    const companyName = $derived(t('sessions.page.act.new_company'));
    const sessionName = $derived(t('sessions.page.act.new_session'));
    const hiddenName = $derived(t('sessions.page.act.show_hidden'));
</script>

<div class="sp-acts">
    <IconButton data-act="new-project" label={projectName} icon="folder-plus" iconSize={14} onclick={onNewProject} />
    <IconButton data-act="new-company" label={companyName} icon="library" iconSize={14} onclick={onNewCompany} />
    <IconButton data-act="new-session" label={sessionName} icon="plus" iconSize={14} onclick={onNewSession} />
    <IconButton data-act="show-hidden" label={hiddenName} icon={showHidden ? 'eye' : 'eye-off'} iconSize={14} pressed={showHidden} onclick={onToggleHidden} />
    {#if showFold}
        <IconButton data-act="fold-all" label={foldName} icon={allOpen ? 'shrink' : 'expand'} iconSize={14} onclick={onToggleAll} />
    {/if}
</div>
