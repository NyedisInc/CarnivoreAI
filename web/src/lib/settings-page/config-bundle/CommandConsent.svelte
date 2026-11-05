
<script lang="ts">
    import Checkbox from '../../base/Checkbox.svelte';
    import type { Translate } from '../../sessions/types';
    import { isChangeKind, visibleCommand, type CommandRow } from './api';
    import { describePart } from './part-words';
    import '../../plugins-page/plugin-pane.css';

    interface Props {
        rows: readonly CommandRow[];
        busy?: boolean;
        ready?: boolean;
        t: Translate;
    }

    let { rows, busy = false, ready = $bindable(false), t }: Props = $props();

    const changesOnly = $derived(rows.length > 0 && rows.every((row) => isChangeKind(row.kind)));

    let ticked = $state<Record<string, boolean>>({});
    ready = false;

    function setTick(key: string, on: boolean): void {
        ticked[key] = on;
        ready = rows.length > 0 && rows.every((row) => ticked[row.key] === true);
    }
</script>

<section class="plp-region" data-cb-commands aria-label={t(changesOnly ? 'settings.configbundle.commands.reach_title' : 'settings.configbundle.commands.title')}>
    <div class="pl-label">{t(changesOnly ? 'settings.configbundle.commands.reach_title' : 'settings.configbundle.commands.title')}</div>
    <p class="plp-warn">{t(changesOnly ? 'settings.configbundle.commands.reach_note' : 'settings.configbundle.commands.note')}</p>
    <ul class="plp-rows">
        {#each rows as row (row.key)}
            <li class="plp-row" class:plp-row--missing={ticked[row.key] !== true} data-cb-command={row.key}>
                <Checkbox
                    data-cb-tick={row.key}
                    aria-label={t(isChangeKind(row.kind) ? 'settings.configbundle.commands.tick_change' : 'settings.configbundle.commands.tick', { name: row.name })}
                    checked={ticked[row.key] === true}
                    disabled={busy}
                    onchange={(e) => setTick(row.key, e.currentTarget.checked)}
                />
                <span class="plp-row__main"
                    ><span class="cmds__name" data-cb-name>{visibleCommand(row.name)}</span><span class="plp-row__sub"
                        >{t(`settings.configbundle.commands.kind.${row.kind}`)} <code class="cmds__id" data-cb-id>{visibleCommand(row.id)}</code></span
                    >
                    {#each row.parts.map((part) => describePart(part, t)) as view, index (index)}
                        <span class="plp-row__sub">{view.label}{#if view.words !== null}{' '}<span data-cb-words>{view.words}</span>{/if}</span>
                        {#if view.text !== ''}<code class="cmds__part">{view.text}</code>{/if}
                        {#if view.tone === 'danger'}<span class="plp-warn" data-cb-danger>{view.warning}</span>{/if}
                        {#if view.tone === 'unknown'}<span class="plp-state" data-tone="warn" data-cb-unknown>{view.warning}</span>{/if}
                        {#if view.was !== null}<span class="plp-row__sub" data-cb-was>{view.was}</span>{/if}
                    {/each}
                </span>
                <span class="plp-tag" data-tone={ticked[row.key] === true ? 'ok' : 'warn'}>
                    {t(ticked[row.key] === true ? 'settings.configbundle.commands.allowed' : 'settings.configbundle.commands.not_allowed')}
                </span>
            </li>
        {/each}
    </ul>
</section>

<style>
    .cmds__name {
        unicode-bidi: isolate;
    }

    .cmds__id {
        font-family: var(--font-mono);
    }

    .cmds__part {
        display: block;
        margin: var(--oc-space-0-5) 0 var(--oc-space-1);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        color: var(--oc-text-primary);
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }
</style>
