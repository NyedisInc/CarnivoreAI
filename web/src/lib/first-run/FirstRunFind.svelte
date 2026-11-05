
<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import { Button, Field } from '../base';
    import { pollJoinStatus, startLook, type Candidate, type JoinStatus } from './join-api';

    let { onNew, onJoinPack, onJoinLink, onJoinHere }: {
        onNew: () => void;
        onJoinPack: (fid: string) => void;
        onJoinLink: (link: string) => void;
        onJoinHere: () => void;
    } = $props();

    type Stage = 'looking' | 'found' | 'none';

    let stage = $state<Stage>('looking');
    let packs = $state<Candidate[]>([]);
    let link = $state('');
    let stopPoll: (() => void) | null = null;
    let gone = false;

    function apply(next: JoinStatus): boolean {
        if (next.state === 'finding' && next.candidates.length > 0) {
            packs = [...next.candidates];
            stage = 'found';
            return true;
        }
        if (next.state === 'failed') {
            stage = 'none';
            return true;
        }
        return false;
    }

    async function look(): Promise<void> {
        stopPoll?.();
        stage = 'looking';
        packs = [];
        const result = await startLook();
        if (gone) return;
        if (!result.ok) {
            stage = 'none';
            return;
        }
        if (!apply(result.status)) stopPoll = pollJoinStatus((s) => (gone ? true : apply(s)));
    }

    function submitLink(event: Event): void {
        event.preventDefault();
        if (link.trim() === '') return;
        const value = link.trim();
        link = '';
        onJoinLink(value);
    }

    onMount(() => void look());
    onDestroy(() => {
        gone = true;
        stopPoll?.();
        link = '';
    });
</script>

{#if stage === 'looking'}
    <p class="first-run__text" role="status" data-first-run="looking">{t('first_run.choose.looking')}</p>
{:else if stage === 'found'}
    {#each packs as pack (pack.fid)}
        <p class="first-run__text" data-first-run="found">{t('first_run.choose.found', { label: pack.label })}</p>
        <Button variant="confirm" data-go data-first-run="found-join" onclick={() => onJoinPack(pack.fid)}>
            {t('first_run.choose.found_join')}
        </Button>
    {/each}
{:else}
    <p class="first-run__text" role="status" data-first-run="none">{t('first_run.choose.none')}</p>
    <form class="first-run__form" onsubmit={submitLink}>
        <label class="first-run__tag" for="first-run-find-link">{t('first_run.choose.link_label')}</label>
        <Field id="first-run-find-link" bind:value={link} autocomplete="off" autocorrect="off" spellcheck={false} data-first-run="find-link" />
        <div class="first-run__actions">
            <Button data-first-run="look-again" onclick={() => void look()}>{t('first_run.choose.look_again')}</Button>
            <Button type="submit" variant="confirm" data-first-run="find-link-go" disabled={link.trim() === ''}>{t('first_run.join.go')}</Button>
        </div>
    </form>
{/if}
<div class="first-run__actions">
    <Button variant={stage === 'found' ? 'secondary' : 'confirm'} data-go data-first-run="choose-new" onclick={onNew}>
        {t('first_run.choose.new')}
    </Button>
    <Button data-go data-first-run="choose-join" onclick={onJoinHere}>{t('first_run.choose.join')}</Button>
</div>
