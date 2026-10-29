
<script lang="ts">
    import Segmented from '../base/Segmented.svelte';
    import type { Translate } from '../sessions/types';
    import { VIEWS, type SessionsView } from './views';

    interface Props {
        view: SessionsView;
        onView: (next: SessionsView) => void;
        t: Translate;
    }
    const { view, onView, t }: Props = $props();

    const ICON: Record<SessionsView, string> = { list: 'list', pivot: 'grid', timeline: 'activity' };
</script>

<Segmented data-view-switch iconOnly label={t('sessions.page.view.label')} value={view} onchange={(next) => onView(next as SessionsView)}
    options={VIEWS.map((v) => ({ value: v, label: t(`sessions.page.view.${v}`), icon: ICON[v], attrs: { 'data-view': v } }))} />
