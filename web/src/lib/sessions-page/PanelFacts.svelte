
<script lang="ts">
    import Tag from '../base/Tag.svelte';
    import type { Translate } from '../sessions/types';
    import type { PageRow } from './filters';
    import { dateWord } from './latest-line';
    import { homeWord } from './panel-format';
    import { transcriptPath } from '../projects-shared/ledger-model';

    interface Props {
        row: PageRow;
        worked: number | null;
        previous: number;
        t: Translate;
        age: (iso: string | null) => string;
    }
    const { row, worked, previous, t, age }: Props = $props();

    const s = $derived(row.s);
    const path = $derived(transcriptPath(s));
    const workedText = $derived(
        worked === null ? t('sessions.page.panel.facts.unmeasured') : worked >= 3600 ? t('sessions.page.group.worked', { h: Math.round(worked / 3600) }) : t('sessions.page.measure.worked_min', { m: Math.max(1, Math.round(worked / 60)) }),
    );
</script>

<section class="sp-pn-sec" id="sp-pn-facts">
    <h3 class="pl-label">{t('sessions.page.panel.facts')}</h3>
    <dl class="sp-pn-dl">
        <dt>{t('sessions.page.panel.facts.folder')}</dt><dd>{homeWord(s.working_dir)}</dd>
        <dt>{t('sessions.page.panel.facts.started')}</dt><dd>{dateWord(s.created_at)} · {age(s.created_at)}</dd>
        <dt>{t('sessions.page.panel.facts.last_active')}</dt><dd>{age(s.last_activity_at)}</dd>
        <dt>{t('sessions.page.panel.facts.worked')}</dt><dd>{workedText}</dd>
        <dt>{t('sessions.page.panel.facts.conversations')}</dt><dd>{previous + 1}</dd>
        {#if s.claude_session_uuid}<dt>{t('sessions.page.panel.facts.conversation_id')}</dt><dd class="sp-pn-mono">{s.claude_session_uuid.slice(0, 13)}</dd>{/if}
        {#if s.tmux_name}<dt>{t('sessions.page.panel.facts.tmux')}</dt><dd class="sp-pn-mono sp-pn-dim">{s.tmux_name}</dd>{/if}
        <dt>{t('projects.page.d.transcript')}</dt>
        <dd data-facts-transcript>
            {#if path}<span class="sp-pn-mono" title={path}>{path}</span>
            {:else if s.has_transcript}{t('projects.page.disk.on')}
            {:else if s.claude_session_uuid}<Tag tone="danger">{t('projects.page.disk.gone')}</Tag> <span class="sp-pn-dim">{t('projects.page.d.gone_why')}</span>
            {:else}<span class="sp-pn-dim">{t('projects.page.d.none_yet')}</span>{/if}
        </dd>
    </dl>
</section>
