
<script lang="ts">
    import Button from '../lib/base/Button.svelte';
    import type { NotesHost } from './notes-host.svelte.js';
    import { refusalMessage } from './admin.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { host }: { host: NotesHost } = $props();

    let attempted = $state(false);

    $effect(() => {
        if (attempted || host.loaded || host.busy) return;
        attempted = true;
        void host.loadNotes('unread');
    });

    const FILTERS: Array<['unread' | 'read', string]> = [
        ['unread', ADMIN_KEYS.notesFilterUnread],
        ['read', ADMIN_KEYS.notesFilterRead],
    ];

    const refusalText = $derived(refusalMessage(host.refusal, t));
</script>

<section class="admin-panel">
    <h2 class="admin-panel__heading">{t(ADMIN_KEYS.notesHeading)}</h2>

    {#if refusalText}
        <p class="admin-refusal" role="alert">{refusalText}</p>
    {/if}

    <div class="admin-filters">
        {#each FILTERS as [status, key] (status)}
            <Button
                aria-pressed={host.status === status}
                onclick={() => void host.loadNotes(status)}
            >
                {t(key)}
            </Button>
        {/each}
    </div>

    {#if !host.loaded}
        <p class="admin-note">{t(ADMIN_KEYS.loading)}</p>
    {:else if host.notes.length === 0}
        <p class="admin-note">{t(ADMIN_KEYS.notesEmpty)}</p>
    {:else}
        <ul class="admin-list">
            {#each host.notes as row (row.note_id)}
                <li class="admin-list__row">
                    <p class="admin-list__name">{row.item_id}</p>
                    <p class="admin-list__meta">
                        {t(ADMIN_KEYS.notesRowBy, {
                            sender: row.sender_login || row.sender_id,
                        })}
                    </p>
                    <p class="admin-list__meta">
                        {t(ADMIN_KEYS.notesRowWhen, {
                            day: (row.created_at || '').slice(0, 10),
                        })}
                    </p>
                    <p class="admin-note-text">{row.text}</p>
                    {#if host.status === 'unread'}
                        <Button
                            onclick={() => void host.mark(row.note_id, true)}
                        >
                            {t(ADMIN_KEYS.notesActionMarkRead)}
                        </Button>
                    {:else}
                        <Button
                            onclick={() => void host.mark(row.note_id, false)}
                        >
                            {t(ADMIN_KEYS.notesActionMarkUnread)}
                        </Button>
                    {/if}
                </li>
            {/each}
        </ul>
    {/if}
</section>
