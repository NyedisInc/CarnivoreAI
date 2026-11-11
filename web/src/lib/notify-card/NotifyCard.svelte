
<script lang="ts">
    import './notify-card.css';
    import { t } from '../i18n/index.svelte';
    import { API_BASE, authFetchBlob } from '../../opscenter/api/auth.svelte';
    import { Button, Field, IconButton } from '../base';
    import Clip from './Clip.svelte';
    import { ACTIONS, KINDS, type NotifyKind } from './contract.gen';
    import Glyph from './Glyph.svelte';
    import { KIND_LIGHT, type NotifyActs, type NotifyCardData } from './types';

    interface Props {
        card: NotifyCardData | null;
        kind?: NotifyKind;
        acts?: NotifyActs;
        body?: string;
        answered?: string;
        typing?: boolean;
        mediaUrl?: string;
        onact?: (id: string, text?: string) => void;
        onclose?: () => void;
    }
    let { card, kind = 'notice', acts, body = '', answered, typing = true, mediaUrl, onact, onclose }: Props = $props();

    const k: NotifyKind = $derived(KINDS.includes(kind) ? kind : 'notice');
    const where = $derived(card ? [card.strip[1], card.strip[2]].filter(Boolean).join(' . ') : t('notify.card.state.no_open'));
    const settle = $derived(answered ?? card?.answered);
    const buttons = $derived(
        (acts ?? ACTIONS[k].map((a) => [a.id, t(a.labelKey)] as const)).map(([id, label]) => ({
            id,
            label,
            typed: ACTIONS[k].some((a) => a.id === id && a.textInput),
        })),
    );
    const DECLINES = /^(no|deny)\b/i;
    let typed: string | null = $state(null);
    let text = $state('');

    function settleLine(code: string): string {
        if (code === 'computer') return t('notify.card.state.settled');
        if (code === 'phone') return t('notify.card.state.already_used');
        if (code === 'auto') return t('notify.card.state.answered_auto');
        if (code === 'elsewhere') return t('notify.card.state.answered_elsewhere');
        return code;
    }
    function settleWhere(code: string): string {
        return ['computer', 'phone', 'auto', 'elsewhere'].includes(code) ? t('notify.card.where.' + code) : (card?.computer ?? '');
    }
    function delta(pair?: number[]): string {
        return pair && pair.length === 2 ? `+${pair[0]} -${pair[1]}` : '';
    }
    let picture: string | undefined = $state();
    let broken = $state(false);
    $effect(() => {
        const wanted = mediaUrl;
        let live = true;
        let made: string | undefined;
        broken = false;
        picture = wanted && !wanted.startsWith(API_BASE + '/') ? wanted : undefined;
        if (wanted?.startsWith(API_BASE + '/'))
            authFetchBlob(wanted.slice(API_BASE.length)).then(
                (blob) => {
                    made = URL.createObjectURL(blob);
                    if (live) picture = made;
                    else URL.revokeObjectURL(made);
                },
                () => {
                    if (live) broken = true;
                },
            );
        return () => {
            live = false;
            if (made) URL.revokeObjectURL(made);
        };
    });
    function size(n: number): string {
        return n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`;
    }
    const mmss = (sec: number) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
    const ext = (name = '') => (name.includes('.') ? name.split('.').pop()!.toLowerCase() : '');
    const path = (url = '') => {
        try {
            return new URL(url).pathname;
        } catch {
            return '';
        }
    };
    function press(id: string, typedAction: boolean) {
        if (typedAction) {
            typed = typed === id ? null : id;
            text = '';
        } else onact?.(id);
    }
    function send() {
        if (typed && text.trim()) onact?.(typed, text.trim());
    }
</script>

{#snippet slashed(value: string)}{#each value.split('/') as part, i}{#if i}/<wbr />{/if}{part}{/each}{/snippet}

{#snippet rows(list: [string, string][])}
    <div class="nc-rows">
        {#each list as [key, value]}
            <div class="nc-row"><span class="nc-k">{t('notify.card.row.' + key)}</span><span class="nc-v">{@render slashed(value)}</span></div>
        {/each}
    </div>
{/snippet}

<section class="nc" data-kind={card ? k : 'empty'} data-answered={settle ? '' : undefined} aria-label={card?.strip[0] ?? t('notify.card.state.nothing')}>
    <div class="nc-bar">
        <span class="nc-led" data-light={settle ? 'green' : card ? KIND_LIGHT[k] : 'gray'}></span>
        <span class="nc-word">{settle ? t('notify.card.state.answered') : card ? card.strip[0] : t('notify.card.state.nothing')}</span>
        <span class="nc-where">{where}</span>
        {#if onclose}<IconButton label={t('notify.card.close')} icon="close" variant="close" onclick={onclose} />{/if}
    </div>
    <div class="nc-body">
        {#if !card}
            <p class="nc-q">{t('notify.card.state.empty')}</p>
        {:else if settle}
            <div class="nc-ans" role="status">
                <span class="nc-glyph"><Glyph name="finished" /></span>
                <div class="nc-ans-t">{settleLine(settle)}</div>
                <div class="nc-ans-d">{t('notify.card.state.closes', { time: card.ts, where: settleWhere(settle) })}</div>
            </div>
        {:else if k === 'yesno'}
            <p class="nc-q">{card.ask}</p>
            {@render rows([['from', `${card.agent} on ${card.computer}`], ['asked', card.ts], ['waiting', t('notify.card.value.waiting_on_answer')]])}
        {:else if k === 'choice'}
            <Clip><p class="nc-q">{card.ask}</p></Clip>
            <div class="nc-opts">
                {#each card.opts ?? [] as [letter, label, desc]}
                    <div class="nc-opt"><span class="nc-key">{letter.toUpperCase()}</span><span class="nc-nm">{label}</span><span class="nc-ds">{desc}</span></div>
                {/each}
            </div>
            {#if card.multi || (card.qcount ?? 1) > 1}<div class="nc-more">{t('notify.card.state.open_to_answer')}</div>{/if}
        {:else if k === 'permission'}
            {#if body}<p class="nc-q">{t('notify.card.lead.permission', { what: body })}</p>{/if}
            <Clip count={card.cmd?.length ?? 0}>
                <div class="nc-cmd" data-long={(card.cmd?.length ?? 0) > 12 ? '' : undefined}>
                    {#each card.cmd ?? [] as line, i}<div>{#if i === 0}<span class="nc-p">{'$ '}</span>{/if}<span class="nc-c">{line}</span></div>{/each}
                </div>
            </Clip>
            {@render rows([['tool', card.tool ?? ''], ['folder', card.dir ?? ''], ['computer', card.computer], ['allow', t('notify.card.value.needs_face_id')]])}
        {:else if k === 'file'}
            <div class="nc-file">
                <div class="nc-pv">{#if picture && !broken}<img src={picture} alt="" onerror={() => (broken = true)} />{:else}<Glyph name="file" />{/if}</div>
                <div>
                    <span class="nc-ty">{ext(card.name) || (card.mime ?? '')}</span>
                    <div class="nc-fnm">{@render slashed(card.name ?? '')}</div>
                    <div class="nc-mt">{card.pages ? t(card.pages === 1 ? 'notify.card.value.file_page' : 'notify.card.value.file_pages', { size: size(card.bytes ?? 0), pages: String(card.pages) }) : size(card.bytes ?? 0)}</div>
                    <div class="nc-mt">{t('notify.card.row.from')} {card.from ?? card.agent}</div>
                </div>
            </div>
            {#if card.head?.length}{@render rows([['first_page', card.head[0]]])}{/if}
        {:else if k === 'link'}
            <div class="nc-dom">{card.host}<small>{path(card.url)}</small></div>
            {#if card.mixed_script}<p class="nc-warn">{t('notify.card.value.mixed_script')}</p>{/if}
            {@render rows([...(card.title ? ([['page', card.title]] as [string, string][]) : []), ['address', card.url ?? ''], ['opens_in', t('notify.card.value.safari')]])}
        {:else if k === 'image' || k === 'video'}
            <div class="nc-media" style:aspect-ratio={k === 'video' ? '3 / 2' : '4 / 3'}>
                {#if picture && !broken}<img src={picture} alt={card.caption ?? ''} onerror={() => (broken = true)} />{:else if k === 'image'}<span class="nc-art"><Glyph name="image" /></span>{/if}
                {#if k === 'video'}
                    <span class="nc-play"><Glyph name="play" /></span>
                    <div class="nc-vbar"><span>0:00 / {mmss(card.dur ?? 0)}</span><i></i></div>
                {/if}
            </div>
            {#if card.caption}<p class="nc-q">{k === 'image' ? t('notify.card.value.image_size', { name: card.caption, w: String(card.w), h: String(card.h) }) : `${card.caption}, ${mmss(card.dur ?? 0)}`}</p>{/if}
        {:else if k === 'finished'}
            <p class="nc-q">{t('notify.card.value.done_in', { mins: String(card.mins) })}</p>
            <div class="nc-files">
                {#each card.files ?? [] as f, i}<div class="nc-frow"><span>{@render slashed(f)}</span>{#if delta(card.stats?.[i])}<span class="nc-delta">{delta(card.stats?.[i])}</span>{/if}</div>{/each}
            </div>
            {#if (card.nfiles ?? 0) > (card.files?.length ?? 0)}<div class="nc-more">{t('notify.card.state.more_count', { count: card.nfiles, unit: t('notify.card.unit.files') })}</div>{/if}
        {:else if k === 'died'}
            <Clip count={card.tail?.length ?? 0}><div class="nc-tail">{#each card.tail ?? [] as l}<div>{l}</div>{/each}</div></Clip>
            <div class="nc-exit">{t('notify.card.value.exit_code', { code: String(card.exit) })}</div>
        {:else if k === 'update'}
            {#if body}<p class="nc-q">{body}</p>{/if}
            {@render rows([['agent', card.agent], ['version', t('notify.card.value.from_to', { from: card.from, to: card.to })], ['sessions', (card.sessions ?? []).join(', ')]])}
        {:else if k === 'appupdate'}
            <div class="nc-ver">{card.to}<small>{t('notify.card.value.you_have', { version: card.from })}</small></div>
            <div class="nc-chg">{#each card.notes ?? [] as n}<div>{n}</div>{/each}</div>
        {:else if k === 'swarm'}
            <Clip><p class="nc-q">{card.ask}</p></Clip>
            <div class="nc-pos">
                {#each card.positions ?? [] as [who, says, side]}<div><b>{side ? t('notify.card.value.on_side', { who: who.toLowerCase(), side }) : who.toLowerCase()}</b>{says}</div>{/each}
            </div>
        {:else if k === 'crosstalk'}
            <div class="nc-thread">
                {#each card.thread ?? [['', card.text ?? '']] as [who, says]}<div>{#if who}<b>{who}</b>{/if}{says}</div>{/each}
            </div>
        {:else if k === 'signin'}
            {#if body}<p class="nc-q">{body}</p>{/if}
            {@render rows([['account', card.provider ? `${card.account ?? ''} (${card.provider})` : (card.account ?? '')], ['reason', card.reason ?? ''], ['waiting', (card.sessions ?? []).join(', ')]])}
        {:else}
            <Clip><p class="nc-q">{card.title}</p><p class="nc-q">{card.body}</p></Clip>
        {/if}
    </div>
    {#if card && !settle && buttons.length}
        <div class="nc-acts">
            {#each buttons.filter((b) => typing || !b.typed) as b (b.id)}
                <Button size="sm" variant={b.id === ACTIONS[k][0]?.id ? 'confirm' : k === 'permission' && DECLINES.test(b.label.trim()) ? 'danger' : 'secondary'} data-act={b.id} onclick={() => press(b.id, b.typed)}>{b.label}</Button>
            {/each}
            {#if typing && typed}
                <form class="nc-reply" onsubmit={(e) => { e.preventDefault(); send(); }}>
                    <Field aria-label={t(k === 'swarm' ? 'notify.card.reply.swarm_placeholder' : 'notify.card.reply.placeholder')} placeholder={t(k === 'swarm' ? 'notify.card.reply.swarm_placeholder' : 'notify.card.reply.placeholder')} bind:value={text} />
                    <Button size="sm" variant="confirm" type="submit" disabled={!text.trim()}>{buttons.find((b) => b.id === typed)?.label}</Button>
                </form>
            {/if}
        </div>
    {/if}
</section>
