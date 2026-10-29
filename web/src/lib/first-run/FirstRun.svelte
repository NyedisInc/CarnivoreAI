
<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import FirstRunJoin from './FirstRunJoin.svelte';
    import { fetchJoinStatus, type JoinStatus } from './join-api';
    import {
        fetchEnrollment,
        navigate,
        readHealth,
        verifyCode,
        watchRestart,
        type Enrollment,
        type EnrollmentFailure,
        type VerifyFailure,
    } from './first-run-api';

    interface AuthHost {
        showLoginForm(): void;
        acceptLogin(response: { access_token: string; refresh_token?: string }): void;
        finishFirstRun(): void;
    }

    type Phase = 'checking' | 'remote' | 'choose' | 'scan' | 'confirm' | 'done' | 'join';

    let { entry = 'first-run' }: { entry?: 'first-run' | 'remote' | 'joined' } = $props();

    let phase = $state<Phase>('checking');
    let enrollment = $state<Enrollment | null>(null);
    let loadFailure = $state<EnrollmentFailure | null>(null);
    let keyOpen = $state(false);
    let copied = $state(false);
    let code = $state('');
    let codeFailure = $state<VerifyFailure | null>(null);
    let busy = $state(false);
    let restarting = $state(false);
    let manual = $state(false);
    let stopWatch: (() => void) | null = null;
    let joinStart = $state<'join' | 'resume' | 'joined'>('join');
    let joinResume = $state<JoinStatus | null>(null);

    const auth = (): AuthHost => (window as unknown as { Auth: AuthHost }).Auth;
    const grouped = $derived(enrollment ? (enrollment.secret.match(/.{1,4}/g) ?? []).join(' ') : '');
    const loadKey = $derived(
        loadFailure === 'restart_pending' ? 'first_run.error.restart_pending' : loadFailure === 'config' ? 'first_run.error.config' : 'first_run.error.load',
    );

    async function load(): Promise<void> {
        loadFailure = null;
        phase = 'checking';
        const result = await fetchEnrollment();
        if (result.ok) {
            enrollment = result.enrollment;
            phase = 'scan';
        } else if (result.failure === 'remote') {
            phase = 'remote';
        } else if (result.failure === 'joined') {
            joinStart = 'joined';
            phase = 'join';
        } else if (result.failure === 'already_paired') {
            auth().showLoginForm();
        } else {
            loadFailure = result.failure;
            phase = 'scan';
        }
    }

    /* already running */
    async function openEntry(): Promise<void> {
        const status = await fetchJoinStatus();
        if (status && (status.state === 'finding' || status.state === 'connecting' || status.state === 'linking' || status.state === 'joined')) {
            joinStart = 'resume';
            joinResume = status;
            phase = 'join';
        } else {
            phase = 'choose';
        }
    }

    onMount(() => {
        if (entry === 'remote') phase = 'remote';
        else if (entry === 'joined') {
            joinStart = 'joined';
            phase = 'join';
        } else void openEntry();
    });
    onDestroy(() => stopWatch?.());

    async function copyKey(): Promise<void> {
        if (!enrollment) return;
        try {
            await navigator.clipboard.writeText(enrollment.secret);
            copied = true;
        } catch {
            copied = false;
        }
    }

    function onCodeInput(event: Event): void {
        const field = event.currentTarget as HTMLInputElement;
        code = field.value.replace(/[^0-9]/g, '');
        field.value = code;
        if (code.length === 6) void submit();
    }

    async function submit(event?: Event): Promise<void> {
        event?.preventDefault();
        if (busy || code.length !== 6) return;
        busy = true;
        codeFailure = null;
        const result = await verifyCode(code);
        busy = false;
        if (!result.ok) {
            codeFailure = result.failure;
            code = '';
            return;
        }
        auth().acceptLogin(result.response);
        phase = 'done';
        await settleAfterPairing();
    }

    async function settleAfterPairing(): Promise<void> {
        const first = await readHealth();
        if (first.ok && first.restartRequired !== true) {
            auth().finishFirstRun();
            return;
        }
        restarting = true;
        stopWatch = watchRestart(!first.ok, {
            settled: (sawDown) => (sawDown ? navigate.reload() : auth().finishFirstRun()),
            manual: () => (manual = true),
        });
    }
</script>

<main class="first-run" data-first-run={phase}>
    <header class="first-run__bar">
        <img class="first-run__wordmark" src="/static/img/carnivore/carnivore-wordmark.png" alt="" />
        <span class="first-run__label">{t('first_run.label')}</span>
    </header>
    <div class="first-run__body">
        {#if phase === 'checking'}
            <p class="first-run__text" role="status">{t('first_run.checking')}</p>
        {:else if phase === 'remote'}
            <span class="first-run__icon"><Icon name="authenticator" size={48} strokeWidth={1.5} /></span>
            <h1 class="first-run__head">{t('first_run.remote.title')}</h1>
            <p class="first-run__text">{t('first_run.remote.body')}</p>
        {:else if phase === 'choose'}
            <span class="first-run__icon"><Icon name="authenticator" size={48} strokeWidth={1.5} /></span>
            <h1 class="first-run__head">{t('first_run.title')}</h1>
            <div class="first-run__actions">
                <button type="button" class="oc-btn oc-btn--confirm first-run__go" data-first-run="choose-new" onclick={() => void load()}>
                    {t('first_run.choose.new')}
                </button>
                <button type="button" class="oc-btn first-run__go" data-first-run="choose-join" onclick={() => ((joinStart = 'join'), (phase = 'join'))}>
                    {t('first_run.choose.join')}
                </button>
            </div>
        {:else if phase === 'join'}
            <FirstRunJoin start={joinStart} resume={joinResume} onBack={() => (phase = 'choose')} />
        {:else if phase === 'scan'}
            <span class="first-run__icon"><Icon name="authenticator" size={48} strokeWidth={1.5} /></span>
            <h1 class="first-run__head">{t('first_run.title')}</h1>
            <p class="first-run__tag">{t('first_run.new.label')}</p>
            <p class="first-run__text">{t('first_run.new.body')}</p>
            {#if enrollment}
                <p class="first-run__text">{t('first_run.scan')}</p>
                <img class="first-run__qr" src={enrollment.qrImage} alt={t('first_run.qr_alt')} width="264" height="264" />
                <button type="button" class="oc-btn" data-first-run="reveal" aria-expanded={keyOpen} onclick={() => (keyOpen = !keyOpen)}>
                    {t('first_run.key.reveal')}
                </button>
                {#if keyOpen}
                    <div class="first-run__key">
                        <code class="first-run__secret" data-first-run="key">{grouped}</code>
                        <button type="button" class="oc-btn" data-first-run="copy" onclick={copyKey}>
                            {copied ? t('first_run.key.copied') : t('first_run.key.copy')}
                        </button>
                    </div>
                {/if}
                <button type="button" class="oc-btn oc-btn--confirm first-run__go" data-first-run="next" onclick={() => (phase = 'confirm')}>
                    {t('first_run.next')}
                </button>
            {:else if loadFailure}
                <p class="first-run__problem" role="alert" data-first-run-error={loadFailure}>{t(loadKey)}</p>
                {#if loadFailure === 'load'}
                    <button type="button" class="oc-btn" data-first-run="retry" onclick={() => void load()}>{t('first_run.retry')}</button>
                {/if}
            {/if}
        {:else if phase === 'confirm'}
            <h1 class="first-run__head">{t('first_run.title')}</h1>
            <form class="first-run__form" onsubmit={submit}>
                <label class="first-run__tag" for="first-run-code">{t('first_run.confirm.label')}</label>
                <input id="first-run-code" class="oc-field first-run__input" value={code} oninput={onCodeInput} maxlength="6"
                    inputmode="numeric" pattern="[0-9]*" autocomplete="one-time-code" autocorrect="off" spellcheck="false"
                    data-first-run="code" disabled={busy} />
                <div class="first-run__actions">
                    <button type="button" class="oc-btn" data-first-run="back" disabled={busy} onclick={() => (phase = 'scan')}>{t('first_run.back')}</button>
                    <button type="submit" class="oc-btn oc-btn--confirm" data-first-run="finish" disabled={busy || code.length !== 6}>
                        {t('first_run.confirm.go')}
                    </button>
                </div>
            </form>
            {#if codeFailure}<p class="first-run__problem" role="alert" data-first-run-error={codeFailure}>{t(`first_run.error.${codeFailure}`)}</p>{/if}
        {:else}
            <p class="first-run__text" role="status" data-first-run="paired">{t('first_run.done')}</p>
            {#if restarting}<p class="first-run__text" data-first-run="restarting">{t('first_run.done.restarting')}</p>{/if}
            {#if manual}
                <p class="first-run__text" data-first-run="manual">{t('first_run.done.manual')}</p>
                <button type="button" class="oc-btn oc-btn--confirm first-run__go" data-first-run="continue" onclick={() => auth().finishFirstRun()}>
                    {t('first_run.done.continue')}
                </button>
            {/if}
        {/if}
    </div>
</main>
