
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import '../settings-page/panel-kit/panel-kit.css';
    import { authFetch } from '../../opscenter/api/auth.svelte';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import { resourcePush } from '../resource-push/boot';

    interface Props {
        t?: Translate;
        fetcher?: typeof authFetch;
    }
    const { t = reactiveT, fetcher = authFetch }: Props = $props();

    interface CommandList {
        commands: string[];
        max_entries: number;
        max_length: number;
    }

    const ROUTE = '/automation-commands';
    const POLL_MS = 15000;
    let list = $state<CommandList | null>(null);
    let draft = $state('');
    let busy = $state(false);
    let problem = $state('');

    async function load(): Promise<void> {
        try {
            list = await fetcher<CommandList>(ROUTE);
        } catch (error) {
            problem = errorText(error);
        }
    }

    $effect(() => {
        void load();
        return resourcePush().pushOrPoll(() => void load(), POLL_MS, ['automation_commands']);
    });

    async function save(commands: string[]): Promise<boolean> {
        busy = true;
        problem = '';
        try {
            list = await fetcher<CommandList>(ROUTE, { method: 'PUT', body: JSON.stringify({ commands }) });
            return true;
        } catch (error) {
            problem = errorText(error);
            return false;
        } finally {
            busy = false;
        }
    }

    async function add(): Promise<void> {
        const text = draft.trim();
        if (!list || text === '') return;
        if (await save([...list.commands, text])) draft = '';
    }

    async function remove(command: string): Promise<void> {
        if (list) await save(list.commands.filter((c) => c !== command));
    }
</script>

<div class="tm" data-automation-commands="panel">
    <p class="tm__sub">{t('settings.automation_commands.hint')}</p>
    {#if list === null && !problem}
        <p class="tm__sub">{t('settings.automation_commands.loading')}</p>
    {:else if list}
        {#if list.commands.length === 0}
            <p class="tm__sub" data-automation-commands="empty">{t('settings.automation_commands.empty')}</p>
        {:else}
            <List label={t('automations.page.commands.title')} data-automation-commands="list">
                {#each list.commands as command (command)}
                    <ListRow>
                        <code class="acmd__text">{command}</code>
                        {#snippet actions()}
                            <Button
                                size="sm"
                                data-automation-commands="remove"
                                disabled={busy}
                                aria-label={t('settings.automation_commands.remove_aria', { command })}
                                onclick={() => void remove(command)}>{t('settings.automation_commands.remove')}</Button
                            >
                        {/snippet}
                    </ListRow>
                {/each}
            </List>
        {/if}
        <form
            class="acmd__add"
            onsubmit={(e) => {
                e.preventDefault();
                void add();
            }}
        >
            <div class="acmd__fld"><Field
                data-automation-commands="input"
                maxlength={list.max_length}
                spellcheck="false"
                autocomplete="off"
                placeholder="/usr/bin/git pull --ff-only"
                aria-label={t('settings.automation_commands.input_aria')}
                bind:value={draft}
            /></div>
            <Button
                type="submit"
                variant="confirm"
                data-automation-commands="add"
                disabled={busy || draft.trim() === '' || list.commands.length >= list.max_entries}>{t('settings.automation_commands.add')}</Button
            >
        </form>
    {/if}
    {#if problem}<p class="tm__problem" role="alert" data-automation-commands="problem">{problem}</p>{/if}
</div>

<style>
    @layer components {
        .acmd__text { flex: 1 1 auto; min-width: 0; font-family: var(--font-mono); font-size: var(--oc-fs-label); color: var(--oc-text-secondary); overflow-wrap: anywhere; }
        .acmd__add { display: flex; flex-wrap: wrap; gap: var(--oc-space-2); align-items: center; }
        .acmd__fld { flex: 1 1 260px; min-width: 0; }
    }
</style>
