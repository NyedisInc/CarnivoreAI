
<script lang="ts">
    import { t as reactiveT, truncatedTip, type Translate } from '../sdk';
    import { errorSentence, type Fetcher } from './crate-api';
    import { keptSubject, skipSentence, warningSentence } from './import-api';
    import { wakeRestoredSession, type ImportReceiptView, type RestoredSession } from './import-receipt';
    import TtyBox from './TtyBox.svelte';

    interface Props {
        receipt: ImportReceiptView;
        t?: Translate;
        fetcher?: Fetcher;
        openProjects?: () => void;
    }
    const SESSIONS_HASH = '#sessions';
    const SHORT_ID = 8;
    const { receipt, t = reactiveT, fetcher, openProjects = () => { window.location.hash = SESSIONS_HASH; } }: Props = $props();

    let status = $state<Record<string, string>>({});
    const project = $derived(receipt.projectName ?? t('cplug.crate.import.result.project_unnamed'));
    const listed = $derived(receipt.sessions.length + receipt.keptBeside.length + receipt.notRestored.length + receipt.warnings.length > 0 || !!receipt.sideFolder);

    function nameOf(session: RestoredSession): string {
        return session.title ?? t('cplug.crate.import.result.untitled', { id: session.sessionUuid.slice(0, SHORT_ID) });
    }

    async function wake(session: RestoredSession): Promise<void> {
        status[session.sessionUuid] = 'waking';
        try {
            const answer = await wakeRestoredSession(session.sessionUuid, fetcher);
            status[session.sessionUuid] = answer.status === 'started' ? 'awake' : answer.detail || answer.status;
        } catch (error) {
            status[session.sessionUuid] = errorSentence(error, t);
        }
    }

    function words(uuid: string): string {
        const s = status[uuid];
        if (s === 'waking') return t('cplug.crate.import.result.waking');
        if (s === 'awake') return t('cplug.crate.import.result.awake');
        return s ?? t('cplug.crate.import.result.asleep');
    }
</script>

<div class="crt-plan" data-crt-import-result={receipt.state}>
    {#if receipt.sessions.length}
        <p class="tm__figs" data-crt-result-heading>
            {t(receipt.sessions.length === 1 ? 'cplug.crate.import.result.session_one' : 'cplug.crate.import.result.sessions', { count: receipt.sessions.length, project })}
        </p>
        {#if receipt.projectRoot}<p class="tm__sub" data-crt-result-root>{t('cplug.crate.import.preview.into', { folder: receipt.projectRoot })}</p>{/if}
    {:else}
        <p class="tm__figs" data-crt-result-heading>{t('cplug.crate.import.result.nothing', { project })}</p>
    {/if}
    {#if listed}
        <TtyBox label={t('cplug.crate.import.result.box_label')} fit>
            <div class="crt-tty__out">
                {#each receipt.warnings as warning (`${warning.code}:${warning.detail}`)}
                    <div class="crt-tty__note">
                        <span class="crt-tty__tag crt-tty__tag--warn">{t('cplug.crate.import.tag.warning')}</span>
                        <p class="crt-tty__text" data-crt-result-warning={warning.code}>{warningSentence(warning, t)}</p>
                    </div>
                {/each}
                {#if receipt.sessions.length}
                    <section class="crt-tty__sec" data-crt-result-sessions>
                        <div class="crt-tty__head"><span>{t('cplug.crate.import.result.sessions_label')}</span><span class="crt-tty__count">{receipt.sessions.length}</span></div>
                        {#each receipt.sessions as session (session.sessionUuid)}
                            {@const name = nameOf(session)}
                            <p class="crt-tty__row" data-crt-result-session={session.sessionUuid}>
                                <span class="crt-tty__name" use:truncatedTip={name}>{name}</span>
                                <span class="crt-tty__fig" data-crt-result-status>{words(session.sessionUuid)}</span>
                                <button type="button" class="oc-btn oc-btn--sm crt-tty__act" data-crt-result-wake={session.sessionUuid}
                                    disabled={status[session.sessionUuid] === 'waking' || status[session.sessionUuid] === 'awake'} onclick={() => void wake(session)}>
                                    {t('cplug.crate.import.result.wake')}
                                </button>
                            </p>
                        {/each}
                    </section>
                {/if}
                {#if receipt.keptBeside.length}
                    <section class="crt-tty__sec" data-crt-result-beside>
                        <div class="crt-tty__head"><span>{t('cplug.crate.import.result.beside')}</span><span class="crt-tty__count">{receipt.keptBeside.length}</span></div>
                        {#each receipt.keptBeside as folder (folder)}<p class="crt-tty__line" title={folder}>{folder}</p>{/each}
                    </section>
                {/if}
                {#if receipt.sideFolder}
                    <section class="crt-tty__sec" data-crt-result-files>
                        <div class="crt-tty__head"><span>{t('cplug.crate.import.result.files')}</span></div>
                        <p class="crt-tty__line">{t('cplug.crate.import.result.files_into', { folder: receipt.sideFolder })}</p>
                        {#if receipt.patchKept}<p class="crt-tty__line" data-crt-result-patch>{t('cplug.crate.import.result.patch_kept')}</p>{/if}
                    </section>
                {/if}
                {#if receipt.notRestored.length}
                    <section class="crt-tty__sec crt-tty__sec--pair" data-crt-result-not-restored>
                        <div class="crt-tty__head"><span>{t('cplug.crate.import.preview.not_restored')}</span><span class="crt-tty__count">{receipt.notRestored.length}</span></div>
                        {#each receipt.notRestored as item (item.what)}
                            {@const what = keptSubject(item.what, t)}
                            {@const why = skipSentence(item.why, t, true)}
                            <p class="crt-tty__row"><span class="crt-tty__name" use:truncatedTip={what}>{what}</span><span class="crt-tty__fig crt-tty__fig--left" title={why}>{why}</span></p>
                        {/each}
                    </section>
                {/if}
            </div>
        </TtyBox>
    {/if}
    <button type="button" class="oc-btn oc-btn--sm crt-plan__act" data-crt-result-open onclick={openProjects}>{t('cplug.crate.import.result.open_projects')}</button>
</div>
