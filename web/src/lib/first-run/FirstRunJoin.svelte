
<script lang="ts">
    import { onDestroy, onMount, tick } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import { legacyAuth } from '../legacy-globals';
    import { Button, Field } from '../base';
    import FirstRunAgent from './FirstRunAgent.svelte';
    import CopyField from '../settings-page/CopyField.svelte';
    import PackOffers from '../pack-offers/PackOffers.svelte';
    import {
        desktopBridge,
        errorKeyFor,
        HELPER_LINE,
        pollJoinStatus,
        postCode,
        startJoin,
        startKnock,
        startLook,
        type Candidate,
        type JoinErrorKey,
        type JoinStatus,
    } from './join-api';
    import { countdownText } from '../pack-knock/countdown';

    interface AuthHost {
        acceptLogin(response: { access_token: string; refresh_token?: string }): void;
        finishFirstRun(): void;
    }

    type Sub = 'join' | 'pick' | 'knocked' | 'joining' | 'join_error' | 'joined' | 'agent';

    let {
        start = 'join',
        value = '',
        resume = null,
        setup = false,
        onBack,
    }: { start?: 'join' | 'resume' | 'joined' | 'knock' | 'link'; value?: string; resume?: JoinStatus | null; setup?: boolean; onBack: () => void } = $props();

    const CELLS = [0, 1, 2, 3, 4, 5];
    const LOCAL_LOGIN_TRIES = 30;

    let sub = $state<Sub>('join');
    let digits = $state<string[]>(['', '', '', '', '', '']);
    let linkMode = $state(false);
    let link = $state('');
    let error = $state<JoinErrorKey | null>(null);
    let status = $state<JoinStatus | null>(null);
    let picked = $state<string | null>(null);
    let busy = $state(false);
    let looking = $state(false);
    let offers = $state<Candidate[]>([]);
    let knockFid = $state<string | null>(null);
    let knocking = $state(false);
    let stopPoll: (() => void) | null = null;
    let knockTimer: ReturnType<typeof setTimeout> | undefined;
    let loginTimer: ReturnType<typeof setTimeout> | undefined;
    let loginTries = 0;
    let gone = false;
    let cellsBox = $state<HTMLElement | null>(null);
    const cell = (i: number): HTMLInputElement | undefined => cellsBox?.querySelectorAll<HTMLInputElement>('[data-first-run="cell"]')[i];

    const auth = (): AuthHost => legacyAuth<AuthHost>();
    const code = $derived(digits.join(''));
    const packName = $derived(status?.main_label ?? t('first_run.join.main_fallback'));
    const stepKey = $derived(knocking ? 'first_run.knock.step.knocking' : looking ? 'first_run.join.step.looking' : status?.state === 'waiting_relay' ? 'first_run.join.step.waiting_relay' : status?.state === 'connecting' ? 'first_run.join.step.connecting' : status?.state === 'linking' ? 'first_run.join.step.linking' : 'first_run.join.step.finding');
    const bridge = $derived(desktopBridge());

    const knockErrorKey = $derived(
        error === 'used_up' || error === 'expired' ? 'first_run.knock.error.gone'
            : error === 'busy' || error === 'rate_limited' || error === 'refused' || error === 'paused' || error === 'incompatible' ? `first_run.knock.error.${error}`
                : `first_run.join.error.${error ?? 'refused'}`,
    );

    function apply(next: JoinStatus): boolean {
        status = next;
        if (next.state === 'knocked') {
            knocking = false;
            knockFid = next.knock_fid ?? knockFid;
            sub = 'knocked';
            armKnockExpiry(next.expires_in);
            void tick().then(() => cell(0)?.focus());
            return true;
        }
        if (next.state === 'joined') {
            enterJoined();
            return true;
        }
        if (next.state === 'failed') {
            looking = false;
            knocking = false;
            error = errorKeyFor(next.error);
            clearSecrets();
            sub = 'join_error';
            return true;
        }
        if (looking && next.state === 'finding' && next.candidates.length > 0) {
            looking = false;
            offers = [...next.candidates];
            sub = 'join';
            return true;
        }
        if (next.state === 'finding' && next.candidates.length > 0) {
            sub = 'pick';
            return true;
        }
        sub = 'joining';
        return false;
    }

    function armKnockExpiry(seconds: number | null): void {
        clearTimeout(knockTimer);
        if (seconds === null) return;
        knockTimer = setTimeout(() => {
            if (sub !== 'knocked') return;
            clearSecrets();
            error = 'expired';
            sub = 'join_error';
        }, Math.max(seconds, 0) * 1000);
    }

    async function knock(fid: string): Promise<void> {
        if (busy) return;
        busy = true;
        error = null;
        knockFid = fid;
        picked = fid;
        knocking = true;
        const result = await startKnock(fid);
        busy = false;
        if (!result.ok) {
            knocking = false;
            error = result.error;
            sub = 'join_error';
            return;
        }
        if (!apply(result.status)) watch();
    }

    function clearSecrets(): void {
        digits = ['', '', '', '', '', ''];
        link = '';
    }

    function watch(): void {
        stopPoll?.();
        stopPoll = pollJoinStatus(apply);
    }

    function enterJoined(): void {
        clearSecrets();
        sub = 'joined';
        if (bridge) void tryLocalLogin();
    }

    async function tryLocalLogin(): Promise<void> {
        loginTries += 1;
        let tokens: { access_token: string; refresh_token?: string } | null = null;
        try {
            tokens = (await bridge?.localLogin?.()) ?? null;
        } catch {
            tokens = null;
        }
        if (gone) return;
        if (tokens) {
            auth().acceptLogin(tokens);
            sub = 'agent';
            return;
        }
        if (loginTries < LOCAL_LOGIN_TRIES) loginTimer = setTimeout(() => void tryLocalLogin(), 1000);
    }

    async function go(event?: Event): Promise<void> {
        event?.preventDefault();
        if (busy) return;
        if (!(linkMode && sub !== 'knocked' ? link.trim() !== '' : code.length === 6)) return;
        busy = true;
        error = null;
        clearTimeout(knockTimer);
        const result = sub === 'knocked'
            ? await postCode(code)
            : await startJoin({
                ...(linkMode ? { link: link.trim() } : { code }),
                ...(picked !== null ? { candidateFid: picked } : {}),
            });
        busy = false;
        if (!result.ok) {
            error = result.error;
            sub = 'join_error';
            clearSecrets();
            return;
        }
        if (!apply(result.status)) watch();
    }

    async function look(): Promise<void> {
        if (busy) return;
        busy = true;
        error = null;
        offers = [];
        picked = null;
        const result = await startLook();
        busy = false;
        if (!result.ok) {
            error = result.error;
            sub = 'join_error';
            return;
        }
        looking = true;
        if (!apply(result.status)) watch();
    }

    function accept(candidate: Pick<Candidate, 'fid'>): void {
        picked = candidate.fid;
        linkMode = false;
        void tick().then(() => cell(0)?.focus());
    }

    function decline(candidate: Pick<Candidate, 'fid'>): void {
        offers = offers.filter((o) => o.fid !== candidate.fid);
        if (picked === candidate.fid) picked = null;
    }

    function pick(candidate: Candidate): void {
        picked = candidate.fid;
        void go();
    }

    function again(): void {
        if (knockFid !== null && error !== 'incompatible') {
            void knock(knockFid);
            return;
        }
        if (error === 'no_pack') linkMode = true;
        picked = null;
        offers = [];
        error = null;
        status = null;
        sub = 'join';
    }

    function onCell(index: number, event: Event): void {
        const field = event.currentTarget as HTMLInputElement;
        const digit = field.value.replace(/[^0-9]/g, '').slice(-1);
        field.value = digit;
        digits[index] = digit;
        if (digit && index < 5) cell(index + 1)?.focus();
        if (code.length === 6) void go();
    }

    function onKey(index: number, event: KeyboardEvent): void {
        if (event.key === 'Backspace' && !digits[index] && index > 0) cell(index - 1)?.focus();
    }

    function onPaste(event: ClipboardEvent): void {
        const text = (event.clipboardData?.getData('text') ?? '').replace(/[^0-9]/g, '').slice(0, 6);
        if (!text) return;
        event.preventDefault();
        digits = CELLS.map((i) => text[i] ?? '');
        cell(Math.min(text.length, 5))?.focus();
        if (text.length === 6) void go();
    }

    onMount(() => {
        if (start === 'joined') {
            status = resume;
            enterJoined();
        } else if (start === 'knock') {
            void knock(value);
        } else if (start === 'link') {
            link = value;
            linkMode = true;
            void go();
        } else if (start === 'resume' && resume) {
            if (resume.state === 'finding' && resume.candidates.length > 0) {
                status = resume;
                sub = 'join';
            } else if (!apply(resume)) watch();
        }
    });
    onDestroy(() => {
        gone = true;
        stopPoll?.();
        clearTimeout(loginTimer);
        clearTimeout(knockTimer);
        clearSecrets();
    });
</script>

{#snippet cells()}
            <div class="first-run__cells" role="group" aria-label={t('first_run.join.label')} bind:this={cellsBox}>
                {#each CELLS as i (i)}
                    <Field value={digits[i]} oninput={(e) => onCell(i, e)}
                        onkeydown={(e) => onKey(i, e)} onpaste={onPaste} maxlength={1} inputmode="numeric" pattern="[0-9]*"
                        autocomplete="one-time-code" autocorrect="off" spellcheck={false} data-first-run="cell" aria-label={`${t('first_run.join.label')} ${i + 1}`} disabled={busy} />
                {/each}
            </div>
{/snippet}

{#if sub === 'join'}
    <h1 class="first-run__head">{t('first_run.title')}</h1>
    <p class="first-run__tag">{t('first_run.join.label')}</p>
    <p class="first-run__text">{t('first_run.join.body')}</p>
    {#if setup}<p class="first-run__text" data-first-run="warning-setup">{t('first_run.join.warning_setup')}</p>{/if}
    <form class="first-run__form" onsubmit={go}>
        {#if linkMode}
            <Field bind:value={link} autocomplete="off" autocorrect="off" spellcheck={false}
                aria-label={t('first_run.join.paste_link')} data-first-run="link" disabled={busy} />
        {:else}
            {@render cells()}
        {/if}
        <PackOffers {offers} {picked} {busy} attr="data-first-run" onLook={look} onYes={accept} onNo={decline} />
        <Button data-first-run="toggle-link" onclick={() => (linkMode = !linkMode)}>
            {linkMode ? t('first_run.back') : t('first_run.join.paste_link')}
        </Button>
        <div class="first-run__actions">
            <Button data-first-run="back" disabled={busy} onclick={onBack}>{t('first_run.back')}</Button>
            <Button type="submit" variant="confirm" data-first-run="join-go" disabled={busy || (linkMode ? link.trim() === '' : code.length !== 6)}>
                {t('first_run.join.go')}
            </Button>
        </div>
    </form>
{:else if sub === 'knocked'}
    <h1 class="first-run__head">{t('first_run.title')}</h1>
    <p class="first-run__tag" data-first-run="knock-title">{t('first_run.knock.title', { name: packName })}</p>
    <p class="first-run__text">{t('first_run.knock.body', { name: packName, fid: status?.own_fid_short ?? '', time: countdownText(status?.expires_in ?? 0, t) })}</p>
    <form class="first-run__form" onsubmit={go}>
        {@render cells()}
        <div class="first-run__actions">
            <Button data-first-run="back" disabled={busy} onclick={onBack}>{t('first_run.back')}</Button>
            <Button type="submit" variant="confirm" data-first-run="join-go" disabled={busy || code.length !== 6}>{t('first_run.join.go')}</Button>
        </div>
    </form>
{:else if sub === 'pick'}
    <h1 class="first-run__head">{t('first_run.title')}</h1>
    <p class="first-run__tag">{t('first_run.join.pick_pack')}</p>
    <ul class="first-run__packs">
        {#each status?.candidates ?? [] as candidate (candidate.fid)}
            <li>
                <Button data-first-run="pack" disabled={busy} onclick={() => pick(candidate)}>
                    {candidate.label}
                </Button>
            </li>
        {/each}
    </ul>
{:else if sub === 'joining'}
    <h1 class="first-run__head">{t('first_run.title')}</h1>
    <p class="first-run__text" role="status" data-first-run="joining">{t(stepKey)}</p>
{:else if sub === 'join_error'}
    <h1 class="first-run__head">{t('first_run.title')}</h1>
    <p class="first-run__problem" role="alert" data-first-run-error={error}>{t(knockFid !== null ? knockErrorKey : `first_run.join.error.${error ?? 'refused'}`)}</p>
    {#if error === 'helper_not_started'}
        <CopyField value={HELPER_LINE} {t} label={t('first_run.join.helper_line_label')} valueAttrs={{ 'data-first-run': 'helper-line' }} />
    {/if}
    <Button data-first-run="retry" onclick={again}>{knockFid !== null && error !== 'incompatible' ? t('first_run.knock.again') : t('first_run.retry')}</Button>
{:else if sub === 'agent'}
    <FirstRunAgent onContinue={() => auth().finishFirstRun()} />
{:else}
    <p class="first-run__text" role="status" data-first-run="joined">{t('first_run.join.done', { name: packName })}</p>
    {#if !bridge}<p class="first-run__text" data-first-run="joined-browser">{t('first_run.join.done_browser', { name: packName })}</p>{/if}
{/if}
