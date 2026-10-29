
<script lang="ts">
    import { onMount } from 'svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import { t } from '../i18n/index.svelte';
    import { openSession } from '../../opscenter/api/host';
    import { providerMark } from '../sessions/agent-marks';
    import { blueprintError, launchBlueprint, previewLaunch } from './api';
    import type { LaunchPreviewResponse, LaunchResponse, MemberPreview, SkillConsent } from './types';

    const SOLO_LAYOUT_DETAIL = 'a layout needs two or more launched sessions';

    interface Props {
        uuid: string;
        name: string;
        close: (value: boolean | null) => void;
    }

    let { uuid, name, close }: Props = $props();

    type Stage = 'loading' | 'preview' | 'confirm_layout' | 'launching' | 'done' | 'error';

    let stage = $state<Stage>('loading');
    let preview = $state<LaunchPreviewResponse | null>(null);
    let result = $state<LaunchResponse | null>(null);
    let loadError = $state('');
    let existingLayoutName = $state('');
    let consentTicks = $state<Record<string, boolean>>({});

    onMount(() => void load());

    async function load(): Promise<void> {
        stage = 'loading';
        try {
            preview = await previewLaunch(uuid);
            stage = 'preview';
        } catch (err) {
            loadError = blueprintError(err).detail;
            stage = 'error';
        }
    }

    function consentKey(memberIndex: number, itemId: string): string {
        return `${memberIndex}:${itemId}`;
    }

    function membersNeedingConsent(members: MemberPreview[]): Array<{ member: MemberPreview; itemId: string }> {
        const out: Array<{ member: MemberPreview; itemId: string }> = [];
        for (const member of members) {
            for (const skill of member.skills) {
                if (skill.needs_consent) out.push({ member, itemId: skill.item_id });
            }
        }
        return out;
    }

    function canLaunch(): boolean {
        return !!preview;
    }

    function consentsBody(): Record<string, SkillConsent> {
        if (!preview) return {};
        const out: Record<string, SkillConsent> = {};
        for (const { member, itemId } of membersNeedingConsent(preview.members)) {
            if (!consentTicks[consentKey(member.index, itemId)]) continue;
            const skill = member.skills.find((s) => s.item_id === itemId);
            const sheet = skill?.consent_sheet;
            const digest = typeof sheet?.['digest'] === 'string' ? (sheet['digest'] as string) : '';
            const bodySha = typeof sheet?.['body_sha'] === 'string' ? (sheet['body_sha'] as string) : '';
            if (!digest || !bodySha) continue;
            out[itemId] = { digest, body_sha: bodySha, scripts: true };
        }
        return out;
    }

    async function doLaunch(overwriteLayout = false): Promise<void> {
        stage = 'launching';
        try {
            result = await launchBlueprint(uuid, { consents: consentsBody(), overwriteLayout });
            stage = 'done';
        } catch (err) {
            const failure = blueprintError(err);
            if (failure.code === 'layout_exists') {
                const named = (err as { payload?: { detail?: { layout?: { name?: string } } } }).payload?.detail?.layout?.name;
                existingLayoutName = named ?? name;
                stage = 'confirm_layout';
                return;
            }
            loadError = failure.detail;
            stage = 'error';
        }
    }

    function openLayout(): void {
        const uuidOfLayout = result?.layout?.['layout_uuid'];
        if (typeof uuidOfLayout === 'string' && uuidOfLayout) {
            window.location.assign(`/layout/${encodeURIComponent(uuidOfLayout)}`);
        }
        close(true);
    }

    const failedCount = $derived(result ? result.members.filter((m) => m.state === 'failed').length : 0);

    const soloSession = $derived(
        result && !result.layout && result.members.length === 1 ? (result.members[0]?.session ?? null) : null,
    );

    function openSoloSession(): void {
        if (soloSession) openSession(soloSession.id, soloSession.tmux_session);
        close(true);
    }

    function memberFolderLine(member: MemberPreview): string {
        if (member.folder.mode === 'worktree' && member.folder.worktree) {
            return t('blueprint.launch.worktree', { path: member.folder.worktree.path, branch: member.folder.worktree.branch });
        }
        if (member.folder.path) return t('blueprint.launch.existing', { path: member.folder.path });
        return '';
    }
</script>

<ModalShell
    title={t('blueprint.launch.title', { name })}
    dismissable={stage !== 'launching'}
    onCancel={() => close(stage === 'done')}
>
    {#if stage === 'loading'}
        <p>{t('blueprint.launch.preview')}...</p>
    {:else if stage === 'error'}
        <p class="bp-launch__error" role="alert">{t('blueprint.launch.failed', { reason: loadError })}</p>
    {:else if stage === 'preview' && preview}
        <p class="oc-label">{t('blueprint.launch.preview')}</p>
        <ul class="bp-launch__list">
            {#each preview.members as member (member.index)}
                {@const mark = providerMark(member.family)}
                {@const path = member.folder.worktree?.path ?? member.folder.path ?? ''}
                <li class="bp-launch__member">
                    <div class="bp-launch__row-head">
                        <span class="bp-launch__mark" data-agent-family={mark.key} role="img" aria-label={mark.label} title={mark.label}
                            >{@html mark.svg}</span
                        >
                        <span class="bp-launch__member-label">{member.label}</span>
                        <span class="bp-launch__row-meta">{member.family_name ?? mark.label}</span>
                    </div>
                    {#if member.folder.mode === 'worktree' || member.skills.length > 0}
                        <div class="bp-launch__chips">
                            {#if member.folder.mode === 'worktree'}
                                <span class="bp-launch__chip">{t('blueprint.session.folder.worktree')}</span>
                            {/if}
                            {#each member.skills as skill (skill.item_id)}
                                <span class="bp-launch__chip">{skill.item_id}</span>
                            {/each}
                        </div>
                    {/if}
                    {#if path}<p class="bp-launch__path">{path}</p>{/if}
                    {#if memberFolderLine(member)}<span class="bp-launch__line">{memberFolderLine(member)}</span>{/if}
                    {#each member.skill_roots_to_create as root (root)}
                        <span class="bp-launch__line bp-launch__line--muted">{t('blueprint.launch.skill_root_create', { path: root })}</span>
                    {/each}
                    {#each member.skills as skill (skill.item_id)}
                        {#if skill.state === 'installed'}
                            <span class="bp-launch__line">{t('blueprint.launch.skill_present', { skill: skill.item_id })}</span>
                        {:else if skill.needs_consent}
                            
                            <div class="bp-launch__consent">
                                <label class="bp-launch__consent-line">
                                    <input
                                        type="checkbox"
                                        checked={!!consentTicks[consentKey(member.index, skill.item_id)]}
                                        onchange={(e) =>
                                            (consentTicks = {
                                                ...consentTicks,
                                                [consentKey(member.index, skill.item_id)]: (e.currentTarget as HTMLInputElement).checked,
                                            })}
                                    />
                                    <span>{t('blueprint.launch.script_consent', { skill: skill.item_id })}</span>
                                </label>
                            </div>
                        {:else}
                            <span class="bp-launch__line">{t('blueprint.launch.skill_install', { skill: skill.item_id })}</span>
                        {/if}
                        {#if skill.instructions_write && skill.state !== 'installed'}
                            
                            <span class="bp-launch__notice" role="note" data-instructions-write-notice>{t('blueprint.launch.skill_instructions_write', { skill: skill.item_id })}</span>
                            {#each skill.instructions_details ?? [] as detail}
                                <span class="bp-launch__notice" data-instructions-write-detail>{detail}</span>
                            {/each}
                            {#if (skill.instructions_more ?? 0) > 0}
                                <span class="bp-launch__notice" data-instructions-write-more>{t('blueprint.launch.skill_instructions_more', { count: skill.instructions_more })}</span>
                            {/if}
                        {/if}
                    {/each}
                    {#each member.problems as problem (problem.code)}
                        <span class="bp-launch__line bp-launch__line--error">{problem.detail}</span>
                    {/each}
                </li>
            {/each}
        </ul>
    {:else if stage === 'confirm_layout'}
        <p role="alert" data-layout-exists>{t('blueprint.launch.layout_exists', { name: existingLayoutName })}</p>
    {:else if stage === 'launching'}
        
        <p role="status">{t('wrappers.import.busy')} &mdash; {t('session.summary.sessions', { count: preview?.members.length ?? 0 })}</p>
    {:else if stage === 'done' && result}
        <ul class="bp-launch__list">
            {#each result.members as member (member.index)}
                <li class="bp-launch__member">
                    {#if member.state === 'launched'}
                        <span class="bp-launch__line bp-launch__line--ok">{t('blueprint.launch.member_ok', { label: member.label })}</span>
                    {:else if member.state === 'woken'}
                        <span class="bp-launch__line bp-launch__line--ok" data-member-woken>{t('blueprint.launch.member_woken', { label: member.label })}</span>
                    {:else if member.state === 'reused'}
                        <span class="bp-launch__line bp-launch__line--ok" data-member-reused>{t('blueprint.launch.member_reused', { label: member.label })}</span>
                    {:else}
                        <span class="bp-launch__line bp-launch__line--error">
                            {t('blueprint.launch.member_failed', { label: member.label, reason: member.problem?.detail ?? '' })}
                        </span>
                    {/if}
                </li>
            {/each}
        </ul>
        {#if failedCount > 0}
            <p class="bp-launch__partial">{t('blueprint.launch.partial', { count: failedCount })}</p>
        {/if}
        {#if result.layout}
            <p class="bp-launch__ok">{t(result.layout_updated ? 'blueprint.launch.done_updated' : 'blueprint.launch.done', { name: result.name })}</p>
        {:else if result.layout_detail && result.layout_detail !== SOLO_LAYOUT_DETAIL}
            <p class="bp-launch__line bp-launch__line--muted">{result.layout_detail}</p>
        {/if}
    {/if}

    {#snippet footer()}
        <!-- padding -->
        {#if stage === 'preview'}
            <button class="modal-btn modal-btn-secondary" onclick={() => close(false)}>{t('blueprint.launch.cancel')}</button>
            <button class="modal-btn modal-btn-primary" disabled={!canLaunch()} onclick={() => void doLaunch(false)}>
                {t('blueprint.launch.confirm')}
            </button>
        {:else if stage === 'confirm_layout'}
            <button class="modal-btn modal-btn-secondary" onclick={() => close(false)}>{t('blueprint.launch.cancel')}</button>
            <button class="modal-btn modal-btn-confirm" onclick={() => void doLaunch(true)}>{t('blueprint.launch.layout_update')}</button>
        {:else if stage === 'launching'}
            <button class="modal-btn modal-btn-secondary" disabled>{t('blueprint.launch.cancel')}</button>
        {:else if stage === 'done'}
            {#if result?.layout}
                <button class="modal-btn modal-btn-primary" onclick={openLayout}>{t('layout.row.open')}</button>
            {:else}
                {#if soloSession}
                    <button class="modal-btn modal-btn-secondary" onclick={() => close(true)}>{t('subagents.status.done')}</button>
                    <button class="modal-btn modal-btn-primary" onclick={openSoloSession}>{t('opscenter.cell.terminal.viewer.open')}</button>
                {:else}
                    <button class="modal-btn modal-btn-primary" onclick={() => close(true)}>{t('subagents.status.done')}</button>
                {/if}
            {/if}
        {:else}
            <button class="modal-btn modal-btn-secondary" onclick={() => close(false)}>{t('blueprint.launch.cancel')}</button>
        {/if}
    {/snippet}
</ModalShell>

<style>
    .bp-launch__list {
        list-style: none;
        margin: 0;
        padding: 0;
    }

    .bp-launch__member {
        border-top: 1px solid var(--oc-border);
        padding: 8px 0;
        display: flex;
        flex-direction: column;
        gap: 3px;
    }

    .bp-launch__member:first-child {
        border-top: none;
    }

    .bp-launch__row-head {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
    }

    .bp-launch__mark {
        display: inline-flex;
        flex: none;
        align-items: center;
        justify-content: center;
        width: 14px;
        height: 14px;
        line-height: 0;
        color: var(--oc-text-secondary);
    }

    .bp-launch__member-label {
        font-weight: 600;
        font-size: 12px;
    }

    .bp-launch__row-meta {
        margin-left: auto;
        color: var(--oc-text-muted);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: var(--oc-tracking-label, 0.6px);
    }

    .bp-launch__chips {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
    }

    .bp-launch__chip {
        padding: 1px 6px;
        border: 1px solid var(--oc-line-faint);
        border-radius: var(--oc-radius-sm, 3px);
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
    }

    .bp-launch__path {
        margin: 0;
        overflow: hidden;
        direction: rtl;
        text-align: left;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: 11px;
    }

    .bp-launch__line {
        font-size: 11px;
        color: var(--oc-text-primary);
    }

    .bp-launch__notice {
        padding: 4px 8px;
        border: 1px solid var(--oc-yellow);
        border-radius: 4px;
        font-size: 11px;
        color: var(--oc-text-primary);
    }

    .bp-launch__line--muted {
        color: var(--oc-text-muted);
    }

    .bp-launch__line--ok {
        color: var(--oc-text-primary);
    }

    .bp-launch__line--error {
        color: var(--oc-coral);
    }

    .bp-launch__consent {
        padding: 6px 8px;
        border: 1px solid var(--oc-yellow);
        border-radius: 4px;
    }

    .bp-launch__consent-line {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        color: var(--oc-text-primary);
        font-size: 11px;
        line-height: 1.4;
        cursor: pointer;
    }

    .bp-launch__consent-line input {
        margin-top: 2px;
        flex-shrink: 0;
        width: 14px;
        height: 14px;
    }

    .bp-launch__partial {
        margin-top: 8px;
        color: var(--oc-coral);
        font-size: 12px;
    }

    .bp-launch__ok {
        margin-top: 8px;
        color: var(--oc-text-primary);
        font-size: 12px;
    }

    .bp-launch__error {
        color: var(--oc-coral);
    }
</style>
