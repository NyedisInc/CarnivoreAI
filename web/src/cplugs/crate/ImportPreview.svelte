
<script lang="ts">
    import { t as reactiveT, truncatedTip, type Translate } from '../sdk';
    import { bytesText } from './crate-api';
    import { unitLabel } from './store-label';
    import { blockerSentence, keptSubject, provenanceSentence, skipSentence, warningSentence, type ImportPlanView } from './import-api';

    interface Props {
        plan: ImportPlanView;
        t?: Translate;
    }
    const { plan, t = reactiveT }: Props = $props();

    const SHOWN = 200;
    const CLASS_TONE: Readonly<Record<string, string>> = {
        write: 'ok', grow: 'grow', present: 'quiet', excluded: 'quiet', not_restored: 'quiet', local_newer: 'warn', conflict: 'bad', live: 'bad',
    };

    const shown = $derived(plan.conversations.slice(0, SHOWN));
    const active = $derived(plan.rows.filter((r) => r.insert + r.present + r.keptLocal > 0));

    function tagText(code: string): string {
        const key = `cplug.crate.import.tag.${code}`;
        const said = t(key);
        return said !== key ? said : code;
    }
</script>

<div class="crt-tty__out" data-crt-import-plan={plan.ok ? 'ok' : 'blocked'}>
    {#if plan.provenance}
        <div class="crt-tty__note" data-crt-import-provenance={plan.provenance}>
            <span class={`crt-tty__tag crt-tty__tag--${plan.provenance === 'own_verified' ? 'ok' : 'warn'}`}>{t(`cplug.crate.import.provenance_label.${plan.provenance}`)}</span>
            <span class="crt-tty__text">{provenanceSentence(plan.provenanceReason, t)}</span>
        </div>
    {/if}
    {#each plan.blockers as blocker (`${blocker.code}:${blocker.detail}`)}
        <div class="crt-tty__note">
            <span class="crt-tty__tag crt-tty__tag--bad">{tagText('blocker')}</span>
            <p class="crt-tty__text crt-tty__text--bad" data-crt-import-blocker={blocker.code}>{blockerSentence(blocker, t)}</p>
            {#if blocker.detail}<p class="crt-tty__text crt-tty__text--dim">{blocker.detail}</p>{/if}
        </div>
    {/each}
    {#each plan.warnings as warning (`${warning.code}:${warning.detail}`)}
        <div class="crt-tty__note">
            <span class="crt-tty__tag crt-tty__tag--warn">{tagText('warning')}</span>
            <p class="crt-tty__text" data-crt-import-warning={warning.code}>{warningSentence(warning, t)}</p>
        </div>
    {/each}
    {#if plan.project}
        {@const p = plan.project}
        <section class="crt-tty__sec" data-crt-import-project>
            <div class="crt-tty__head"><span>{t('cplug.crate.import.preview.project')}</span></div>
            {#if p.action}<p class="crt-tty__line crt-tty__line--bright">{t(`cplug.crate.import.preview.action.${p.action}`, { name: p.name ?? '' })}</p>{/if}
            {#if p.rootTo}<p class="crt-tty__line" data-crt-import-root title={p.rootTo}>{t('cplug.crate.import.preview.into', { folder: p.rootTo })}</p>{/if}
            {#if p.nameChangedTo}<p class="crt-tty__line" data-crt-import-renamed>{t('cplug.crate.import.preview.renamed', { name: p.nameChangedTo })}</p>{/if}
            {#if plan.projectFolder?.files}
                {@const f = plan.projectFolder}
                <p class="crt-tty__line" data-crt-import-project-files={f.files}>
                    {#if f.files === 'already_here'}
                        <span class="crt-tty__tag crt-tty__tag--quiet">{tagText('present')}</span>
                        {t('cplug.crate.import.preview.files_here', { count: f.matching ?? 0 })}
                    {:else}
                        {#if (f.matching ?? 0) > 0}{t('cplug.crate.import.preview.files_mixed', { here: f.matching ?? 0, differ: f.differing ?? 0 })}{/if}
                        {t(f.files === 'into_project_folder' ? 'cplug.crate.import.project_files_into' : 'cplug.crate.import.project_files_beside', { folder: f.files === 'into_project_folder' ? f.path : (f.side ?? '') })}
                    {/if}
                </p>
            {/if}
            {#if p.adoptions > 0}<p class="crt-tty__line" data-crt-import-adoptions>{t('cplug.crate.import.preview.adoptions', { count: p.adoptions })}</p>{/if}
        </section>
    {/if}
    {#if plan.cleanup?.needsGuard}
        <div class="crt-tty__note">
            <span class="crt-tty__tag crt-tty__tag--warn">{tagText('warning')}</span>
            <p class="crt-tty__text" data-crt-import-cleanup-warning>{t('cplug.crate.import.preview.cleanup_warning', { count: plan.cleanup.filesOlder, period: plan.cleanup.periodDays, oldest: plan.cleanup.oldestDays })}</p>
        </div>
    {/if}
    {#if plan.restamp && plan.conversations.some((c) => c.cls === 'write' || c.cls === 'grow')}
        <p class="crt-tty__line" data-crt-import-restamp>{t('cplug.crate.import.preview.restamp')}</p>
    {/if}
    {#if plan.backups}
        {@const total = plan.backups.conversations.reduce((n, c) => n + c.points, 0) + plan.backups.folders.reduce((n, c) => n + c.points, 0)}
        <section class="crt-tty__sec" data-crt-import-backups>
            <div class="crt-tty__head"><span>{t('cplug.crate.import.preview.backups')}</span><span class="crt-tty__count">{total}</span></div>
            {#each plan.backups.conversations as row (row.id)}
                {@const name = plan.conversations.find((c) => c.id === row.id)?.title ?? row.id}
                <p class="crt-tty__row" data-crt-import-backup={row.id} data-crt-import-backup-status={row.status}>
                    <span class="crt-tty__name" use:truncatedTip={name}>{name}</span>
                    <span class="crt-tty__fig">
                        {#if row.status === 'not_restored'}
                            {t('cplug.crate.import.preview.backups_not_restored', { count: row.points, why: skipSentence(row.reason ?? '', t) })}
                        {:else if row.status === 'present'}
                            {t('cplug.crate.import.preview.backups_present', { count: row.points })}
                        {:else}
                            {t('cplug.crate.import.preview.backups_points', { count: row.points, files: row.files, size: bytesText(row.bytes) })}
                        {/if}
                    </span>
                </p>
            {/each}
            {#each plan.backups.folders as row (row.unit)}
                <p class="crt-tty__row" data-crt-import-backup={row.unit} data-crt-import-backup-status={row.status}>
                    <span class="crt-tty__name" use:truncatedTip={unitLabel(row.unit, t)}>{unitLabel(row.unit, t)}</span>
                    <span class="crt-tty__fig">
                        {#if row.status === 'not_restored'}
                            {t('cplug.crate.import.preview.backups_not_restored', { count: row.points, why: skipSentence(row.reason ?? '', t) })}
                        {:else if row.status === 'present'}
                            {t('cplug.crate.import.preview.backups_present', { count: row.points })}
                        {:else}
                            {t('cplug.crate.import.preview.backups_points', { count: row.points, files: row.files, size: bytesText(row.bytes) })}
                        {/if}
                    </span>
                </p>
            {/each}
        </section>
    {/if}
    {#if plan.mapping.length}
        <section class="crt-tty__sec crt-tty__sec--pair" data-crt-import-mapping>
            <div class="crt-tty__head"><span>{t('cplug.crate.import.preview.mapping')}</span><span class="crt-tty__count">{plan.mapping.length}</span></div>
            {#each plan.mapping as rule (rule.from)}
                <p class="crt-tty__row"><span class="crt-tty__name" use:truncatedTip={rule.from}>{rule.from}</span><span class="crt-tty__fig crt-tty__fig--left" title={rule.to}>{rule.to}</span></p>
            {/each}
        </section>
    {/if}
    {#if plan.conversations.length}
        <section class="crt-tty__sec" data-crt-import-conversations>
            <div class="crt-tty__head"><span>{t('cplug.crate.import.preview.conversations')}</span><span class="crt-tty__count">{plan.conversations.length}</span></div>
            {#each shown as conversation (conversation.id)}
                {@const name = conversation.title ?? conversation.id}
                <p class="crt-tty__row" data-crt-import-conversation={conversation.id} data-crt-import-class={conversation.cls}>
                    <span class="crt-tty__name" use:truncatedTip={name}>{name}</span>
                    <span class="crt-tty__fig">{t(`cplug.crate.import.preview.resume.${conversation.resume}`)}</span>
                    <span class={`crt-tty__tag crt-tty__tag--${CLASS_TONE[conversation.cls] ?? 'quiet'}`} title={t(`cplug.crate.import.preview.class.${conversation.cls}`)}>{tagText(conversation.cls)}</span>
                </p>
                {#if conversation.cls === 'not_restored' && conversation.reason}
                    <p class="crt-tty__line" data-crt-import-conversation-reason={conversation.reason}>{skipSentence(conversation.reason, t, true)}</p>
                {/if}
            {/each}
            {#if plan.conversations.length > SHOWN}
                <p class="crt-tty__line" data-crt-import-more>{t('cplug.crate.import.preview.more', { count: plan.conversations.length - SHOWN })}</p>
            {/if}
        </section>
    {/if}
    {#if active.length}
        <section class="crt-tty__sec" data-crt-import-rows>
            <div class="crt-tty__head"><span>{t('cplug.crate.import.preview.rows')}</span><span class="crt-tty__count">{active.length}</span></div>
            {#each active as row (row.table)}
                <p class="crt-tty__row" data-crt-import-table={row.table}>
                    <span class="crt-tty__name" use:truncatedTip={row.table}>{row.table}</span>
                    <span class="crt-tty__fig">{t('cplug.crate.import.preview.row_counts', { insert: row.insert, present: row.present, kept: row.keptLocal })}</span>
                    <span class={`crt-tty__tag crt-tty__tag--${row.insert > 0 ? 'ok' : 'quiet'}`}>{tagText(row.insert > 0 ? 'write' : 'present')}</span>
                </p>
            {/each}
        </section>
    {/if}
    {#if plan.heldBack}
        <div class="crt-tty__note">
            <span class="crt-tty__tag crt-tty__tag--quiet">{tagText('held_back')}</span>
            <p class="crt-tty__text" data-crt-import-held-back>{t('cplug.crate.import.preview.held_back', { memory: plan.memoryFiles ?? 0, plans: plan.plans ?? 0 })}</p>
        </div>
    {/if}
    {#if plan.notRestored.length}
        <section class="crt-tty__sec crt-tty__sec--pair" data-crt-import-not-restored>
            <div class="crt-tty__head"><span>{t('cplug.crate.import.preview.not_restored')}</span><span class="crt-tty__count">{plan.notRestored.length}</span></div>
            {#each plan.notRestored as item (item.what)}
                {@const why = skipSentence(item.why, t, true)}
                <p class="crt-tty__row"><span class="crt-tty__name" use:truncatedTip={keptSubject(item.what, t)}>{keptSubject(item.what, t)}</span><span class="crt-tty__fig crt-tty__fig--left" title={why}>{why}</span></p>
            {/each}
        </section>
    {/if}
</div>
