<!--
  RunningSessionName - the row's name, and the inline editor it becomes.

  THIS EDITS THE LABEL, NOT THE HANDLE. `sessions.title` is free-form text
  a human typed; the tmux name is an internal handle derived from it once,
  at creation, and never moved again. This control used to seed itself
  from that handle and enforce the handle's own `^[A-Za-z0-9_-]{1,64}$`
  against it, which did two things: it refused "Image Tool" in the
  browser against a server that accepts it happily, and it showed a user
  who HAD a label the handle instead, so a plain Enter stored a
  handle-derived string over their own label. Silent data loss.

  THE SEED IS THE RENDERED TEXT. Display and seed agree by construction
  rather than by two functions happening to match: both read
  `displayName`, so if the row's display half ever regresses to the
  handle, the seed regresses with it and one test catches both.

  A REPAINT NO LONGER DELETES WHAT THE USER IS TYPING, AND THAT IS WHY
  `client/js/session-list-busy-guard.js` IS GONE. Every legacy branch
  ended in an `innerHTML` write over this whole list, so a poll tick that
  landed while the input was open destroyed the field, the caret and the
  typed text with no error anywhere - and the signature diff did not save
  it, because a status flip on any OTHER row is a real change and paints.
  The guard's answer was to SKIP the paint, which bought correctness with
  staleness. Here the input is a node Svelte owns and a tick touches only
  the values that moved, so there is nothing to destroy and nothing to
  skip.

  BLUR SAVES, ESCAPE CANCELS, ENTER SAVES, and an UNCHANGED value writes
  nothing on any of the three. See ./running-actions.ts::saveRename for
  why the unchanged guard is measured against the seed.
-->
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import { RUNNING_SESSION_KEYS } from '../../../../client/js/labels/running-session.js';
    import { saveRename } from './running-actions';
    import type { RunningHost } from './running-host';
    import type { Translate } from '../sessions/types';

    interface Props {
        displayName: string;
        renameKey: string | null;
        editing: boolean;
        onclose: () => void;
        host: RunningHost;
        t?: Translate;
    }

    let {
        displayName,
        renameKey,
        editing,
        onclose,
        host,
        t = reactiveT,
    }: Props = $props();

    let error = $state<string | null>(null);
    let settled = $state(false);
    let input = $state<HTMLInputElement | null>(null);

    $effect(() => {
        const el = input;
        if (!el) return;
        el.focus();
        el.select();
    });

    function cancel(): void {
        if (settled) return;
        settled = true;
        error = null;
        onclose();
    }

    async function save(): Promise<void> {
        if (settled || !renameKey || !input) return;
        const typed = input.value;
        const outcome = await saveRename(
            renameKey, typed, displayName, host, t,
        );
        if (outcome.state === 'refused') {
            error = outcome.reason;
            if (input) {
                input.focus();
                input.select();
            }
            return;
        }
        settled = true;
        error = null;
        onclose();
    }

    /* Escape cancels */
    function onKey(event: KeyboardEvent): void {
        event.stopPropagation();
        if (event.key === 'Enter') {
            event.preventDefault();
            void save();
        } else if (event.key === 'Escape') {
            event.preventDefault();
            cancel();
        }
    }
</script>

{#if editing && renameKey}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <input
        bind:this={input}
        type="text"
        class="running-session-rename-input"
        value={displayName}
        maxlength={host.labelMaxChars()}
        spellcheck="false"
        autocomplete="off"
        aria-label={t(RUNNING_SESSION_KEYS.renameInputAria)}
        onkeydown={onKey}
        onclick={(event) => event.stopPropagation()}
        onblur={() => void save()}
    />
    {#if error}
        <span class="running-session-rename-error">{error}</span>
    {/if}
{:else}
    <span class="running-session-name">{displayName}</span>
{/if}
