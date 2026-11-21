
<script lang="ts">
    import { Segmented } from '../base';
    import type { Translate } from '../sessions/types';
    import { sessionPlaceApi, type SessionPlaceApi } from '../session-place/api';

    interface Props {
        t: Translate;
        workingDir: string;
        agentType?: string;
        computer: string;
        note: string;
        api?: SessionPlaceApi;
    }
    let { t, workingDir, agentType = '', computer = $bindable(), note = $bindable(), api: injected }: Props = $props();
    // svelte-ignore state_referenced_locally
    const api: SessionPlaceApi = injected ?? sessionPlaceApi;

    let preview = $state('');

    function read(question: { working_dir: string; agent_type?: string }, live: () => boolean): void {
        preview = t('launch_picker.computer.reading');
        api.explain(question).then((p) => {
            if (!live()) return;
            if (p.decision === 'remote') preview = t('launch_picker.computer.preview_remote', { computer: p.label || p.computer || '', reason: p.reason });
            else if (p.decision === 'here') preview = t('launch_picker.computer.preview_here', { reason: p.reason });
            else preview = t('launch_picker.computer.preview_refused', { reason: p.reason });
        }).catch(() => { if (live()) preview = t('launch_picker.computer.unread'); });
    }

    $effect(() => {
        const question = { working_dir: workingDir, ...(agentType ? { agent_type: agentType } : {}) };
        let alive = true;
        read(question, () => alive);
        return () => { alive = false; };
    });
    $effect(() => { note = computer === 'auto' ? preview : ''; });
</script>


<div>
<Segmented
    label={t('launch_picker.computer.label')}
    bind:value={computer}
    options={[
        { value: 'here', label: t('launch_picker.computer.here'), attrs: { 'data-lpm-computer': 'here' } },
        { value: 'auto', label: t('launch_picker.computer.auto'), attrs: { 'data-lpm-computer': 'auto' } },
    ]}
/>
</div>
