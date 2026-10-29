
<script lang="ts">
    import Button from '../base/Button.svelte';
    import IconButton from '../base/IconButton.svelte';
    import {
        adoptAttributed,
        browserHost,
        close,
        declineAttributed,
        isClosed,
        loadPrompt,
        viewFor,
        type AttributionHost,
        type SessionAttributionPrompt,
    } from './attribution';
    import { t } from '../i18n/index.svelte';

    interface Props {
        host?: AttributionHost;
    }

    let { host = browserHost() }: Props = $props();

    /* could not */
    let prompt = $state<SessionAttributionPrompt | null>(null);
    /*  hidden  */
    let picking = $state(false);
    let hasClosed = $state(isClosed());
    let ticked = $state<Record<string, boolean>>({});

    const view = $derived(viewFor(prompt, host, hasClosed));

    export async function refresh(): Promise<void> {
        prompt = await loadPrompt(host);
        picking = false;
        ticked = {};
    }

    function allNames(): string[] {
        return view.kind === 'pending' ? view.rows.map((r) => r.tmuxName) : [];
    }

    function pickedNames(): string[] {
        return allNames().filter((name) => ticked[name] !== false);
    }

    /* running sessions */
    async function adopt(names: string[]): Promise<void> {
        if (names.length === 0) return;
        await adoptAttributed(names, host);
        await refresh();
        host.refreshRunningSessions();
    }

    async function decline(names: string[]): Promise<void> {
        if (names.length === 0) return;
        await declineAttributed(names, host);
        await refresh();
    }

    function dismiss(): void {
        close();
        hasClosed = true;
    }

    void refresh();
</script>

{#if view.kind === 'unavailable'}
    <div
        class="attribution-prompt attribution-prompt--unknown"
        data-attribution-state="unavailable"
    >{view.notice}</div>
{:else if view.kind === 'pending'}
    <section
        class="attribution-prompt"
        class:attribution-prompt--picking={picking}
        data-attribution-state="pending"
        aria-label={t('attribution.pending.label')}
    >
        <IconButton label={t('attribution.close.label')} variant="close" icon="close" id="attribution-prompt-close" onclick={dismiss} />
        <p class="attribution-prompt__notice">{view.notice}</p>
        <ul class="attribution-prompt__list">
            {#each view.rows as row (row.tmuxName)}
                <li class="attribution-prompt__row" data-tmux-name={row.tmuxName}>
                    <label class="attribution-prompt__pick">
                        <input
                            type="checkbox"
                            class="attribution-prompt__check"
                            data-tmux-name={row.tmuxName}
                            checked={ticked[row.tmuxName] !== false}
                            onchange={(event) => {
                                ticked[row.tmuxName] = event.currentTarget.checked;
                            }}
                        />
                        <span
                            class="attribution-prompt__name"
                        >{row.shown}</span>
                    </label>
                    <span class="attribution-prompt__meta">started {row.started}</span>
                    <span class="attribution-prompt__why" data-reason={row.reason}
                    >{row.why}</span>
                    {#if row.hints.length}
                        <ul class="attribution-prompt__hints">
                            {#each row.hints as hint}
                                <li class="attribution-prompt__hint">{hint}</li>
                            {/each}
                        </ul>
                    {/if}
                </li>
            {/each}
        </ul>
        <div
            class="attribution-prompt__actions attribution-prompt__actions--all"
            hidden={picking}
        >
            <Button variant="confirm"
                id="attribution-adopt-all"
                onclick={() => adopt(allNames())}
            >adopt all</Button>
            <Button
                id="attribution-choose"
                onclick={() => { picking = true; }}
            >choose individually</Button>
            <Button
                id="attribution-decline-all"
                onclick={() => decline(allNames())}
            >leave as external</Button>
        </div>
        <div
            class="attribution-prompt__actions attribution-prompt__actions--picked"
            hidden={!picking}
        >
            <Button variant="confirm"
                id="attribution-adopt-picked"
                onclick={() => adopt(pickedNames())}
            >adopt the ticked ones</Button>
            <Button
                id="attribution-decline-picked"
                onclick={() => decline(pickedNames())}
            >leave the ticked ones external</Button>
        </div>
        <p class="attribution-prompt__footnote"
        >closing this without answering brings it back next time. leaving them external is remembered.</p>
    </section>
{/if}
