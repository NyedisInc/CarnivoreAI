
export const LETTERS = Object.freeze([
    { name: 'new-agent', letter: 'n', meaning: 'new agent or session, show conversation backups, show status counts', verbs: ['new'], ids: ['new-session', 'new-in-folder', 'new-agent', 'agent', 'sort:name', 'show-restores', 'show-counts'], shares: 'show conversation backups is the timeline widget menu and show counts the TM Mark II widget menu, neither of which draws a new item' },
    { name: 'new-terminal', letter: 't', meaning: 'new terminal', ids: ['new-terminal-here', 'terminal', 'sort:project', 'show-stats', 'show-shells'], shares: 'sort and show-stats are widget and view menu items, no new-terminal item there; show shells is the war room widget menu' },
    { name: 'new-browser', letter: 'b', meaning: 'new browser, bookmark, background, blueprint, show browsers, show bookmarks, back (close the open crosstalk conversation)', ids: ['browser', 'bookmark', 'load-blueprint', 'background', 'show-browsers', 'show-bookmarks', 'close-thread'], shares: 'show browsers is the war room widget menu and close the conversation the crosstalk widget menu, each of which draws none of the others; show bookmarks is the timeline widget menu, which also draws bookmark this: the clash rule keeps b on show bookmarks (earlier) and bookmark this takes its label\'s first free letter' },
    { name: 'pin', letter: 'p', meaning: 'pin, project colors, open a file path', ids: ['pin', 'pin-bar', 'project', 'scope:project', 'project-colors', 'open-path'], shares: 'the + menu draws project and no pin; this project is the crosstalk widget menu scope choice, which draws no pin; project colors is the TM Mark II widget menu, which draws no pin; open path is the files widget menu, which draws none of the other p items' },
    { name: 'go-to', letter: 'g', meaning: 'go: send to, group icon, art, new group, git ignored files, group by area, open in terminal app', ids: ['send-to', 'group-icon', 'regenerate-art', 'group', 'git-ignored-files', 'group-by-area', 'open-in-terminal'], shares: 'the group heading draws the icon, the row menu send to, the + menu new group, the files widget menu git ignored files, the TM Mark II widget menu group by area, the terminal widget menu open in terminal app (o is its pop out)' },
    { name: 'fork', letter: 'f', meaning: 'fork, focus the main window, fold everything inside', ids: ['fork', 'focus-main-window', 'fold-inside'], shares: 'focus is the widget menu, fork the row menu, fold everything inside the project, company and group heading menus, none of which draws a fork' },
    { name: 'color', letter: 'c', meaning: 'color, customize (the group heading menu branch), change the folder a session lives in, collapse all folders, fold this section, show paired computers, show compacts, accordion', ids: ['pick-color', 'colour', 'color', 'color-style', 'move-to-folder', 'collapse-all', 'fold', 'show-computers', 'show-compacts', 'accordion', 'customize'], shares: 'customize is the group heading menu branch that holds colour, whose own level is a different menu; fold is the section heading menu, which draws no color; accordion is the TM Mark II widget menu; show compacts is the timeline widget menu; show computers is the war room widget menu; colour is a Layout or group row item and move to folder a live agent row item: no row menu draws both (every other letter is taken by an item a live agent row draws); collapse all is the files widget menu' },
    { name: 'add-to', letter: 'a', meaning: 'add to (file this item into a group or company)', ids: ['add-to', 'add-to-company', 'move-to-group', 'turn-on-agent', 'turn-off-agent', 'sort:activity', 'account_page', 'signin', 'scope:all'], shares: 'agent switches, the sort, the account menu and the crosstalk scope choice never sit beside a filing item' },
    { name: 'add-members', letter: '+', meaning: 'add members (put agents or groups into a layout or group)', ids: ['add-members'], shares: 'add members is the row and heading menus, extend a row the edit-mode widget menu' },
    { name: 'remove-from', letter: '-', meaning: 'remove from group or company, pull back a row', ids: ['remove-from-group', 'remove-from-company', 'pull-back-row'], shares: 'pull back is the edit-mode widget menu, remove from the row and heading menus' },
    { name: 'move-up', letter: '[', meaning: 'move up', ids: ['move-up', 'widget-move-up'] },
    { name: 'move-down', letter: ']', meaning: 'move down', ids: ['move-down', 'widget-move-down'] },
    { name: 'mute', letter: 'm', meaning: 'mute, move to another bar or the drawer, master all', ids: ['mute', 'move-to-drawer', 'move-to-bar', 'master_all'], shares: 'mute is the row menu, the move items the widget menu, master all the account menu' },
    { name: 'zoom', letter: 'z', meaning: 'reconnect tools, zoom', ids: ['reconnect-mcp', 'zoom'], shares: 'zoom is the terminal widget menu, reconnect the row menu' },
    { name: 'open', letter: 'o', meaning: 'open: pop out, open the drawer, change agent type, share, show open, show completed, sign out, open a conversation', ids: ['popout', 'pop-out', 'open-drawer', 'change-agent-type', 'share-read-only', 'show-open', 'show-completed', 'signout', 'open-conversation'], shares: 'each is the only "open" verb of its menu; show completed is the TM Mark II widget menu, which draws no other o item' },
    { name: 'wake', letter: 'w', meaning: 'wake, keep awake, write (a notepad in edit mode), whole file (not its diff), rewind', ids: ['keep-awake', 'wake', 'mode:edit', 'whole-file', 'rewind-here'], shares: 'edit mode is the notes widget menu, whole file the files widget menu and rewind here the timeline widget menu, which draw no wake' },
    { name: 'sleep', letter: 's', meaning: 'sleep, save as blueprint, save now, shape, show sleeping, show the global folder, show the status bar, download a file', ids: ['sleep', 'save-blueprint', 'save', 'shape', 'show-sleeping', 'show-global-folder', 'scope:session', 'status-bar', 'download'], shares: 'download is the file row menu, which draws no sleep or save (every letter is taken by an item a file row draws); the status bar is the TM Mark II widget menu, which draws no sleep or save; this session is the crosstalk widget menu scope choice, which draws none of the others; shape is the swarm node menu, show sleeping the view menu, sleep and save as blueprint the row and heading menus, save now the notes widget menu, show the global folder the files widget menu' },
    { name: 'restart', letter: 'h', meaning: 'restart the agent, show header', ids: ['restart', 'show-header'], shares: 'show header is the widget menu' },
    { name: 'edit-layout', letter: 'e', meaning: 'edit layout, done editing, update and restart, edit the filter of a group', ids: ['toggle-edit-layout', 'layout', 'edit-layout', 'done-editing', 'update-restart', 'group-rule'], shares: 'update and restart is the row menu only; the group filter is the group heading menu, which draws none of the others' },
    { name: 'later', letter: 'l', meaning: 'later: schedule; show leaders; lock this device; list project first; share a link to a review board', ids: ['schedule', 'sort:last_used', 'show-leaders', 'logout', 'list-project-first', 'share-link'], shares: 'the account and view menus draw neither schedule nor the sort; list project first is the files widget menu; share link is the page row menu, which has no schedule' },
    { name: 'close', letter: 'k', meaning: 'close, kill, remove from the bar', ids: ['close', 'close-widget', 'remove-widget', 'close-tab'] },
    { name: 'copy', letter: 'y', meaning: 'copy (yank), open a copy of a conversation backup', verbs: ['copy'], ids: ['copy-path', 'copy-session-id', 'open-copy'] },
    { name: 'show-path', letter: 'i', meaning: 'show path, set image, include dot files, edit the rail icons', ids: ['show-path', 'set-image', 'include-dot-files', 'edit-rail-icons', 'done-rail-icons'], shares: 'set image is the swarm node menu, include dot files the files widget menu, the rail icons the sidebar rail menu' },
    { name: 'crosstalk', letter: 'x', meaning: 'x-talk, remove image, clear color', ids: ['crosstalk', 'remove-image', 'clear-company-color'], shares: 'image and color clearing never sit beside crosstalk' },
    { name: 'quiet', letter: 'q', meaning: 'quiet: messaging; squeeze long sleeps', ids: ['messaging', 'squeeze-sleeps'], shares: 'the same bind-or-silence slot; squeeze long sleeps is the timeline widget menu, which draws neither' },
    { name: 'mark-unread', letter: 'u', meaning: 'mark unread, mark read', ids: ['mark-unread', 'mark-read'], shares: 'mark read is drawn only on a finished unread row, beside the mark unread toggle (clear unread); the earlier item keeps u and the clash rule gives the later one a free letter' },
    { name: 'project-lead', letter: 'j', meaning: 'make project lead, just changes', ids: ['huddle-project-lead', 'just-changes'], shares: 'just changes is the files widget menu, project lead the row menu' },
    { name: 'rename', letter: 'r', meaning: 'rename, recent sort, reload, show restarts, mark all as read', verbs: ['rename'], ids: ['sort:recent', 'reload', 'show-restarts', 'mark-all-read'], shares: 'reload is the files widget menu, which draws no rename or sort; show restarts is the timeline widget menu and mark all as read the crosstalk widget menu, neither of which draws a rename or sort' },
    { name: 'archive', letter: 'v', meaning: 'archive, show archived, view (a notepad in preview mode)', verbs: ['archive', 'unarchive'], ids: ['show-archived', 'mode:preview'], shares: 'the view menu draws no archive verb; preview is the notes widget menu, which draws neither' },
    { name: 'delete', letter: 'd', meaning: 'delete', verbs: ['delete'], ids: [] },
    { name: 'settings', letter: ',', meaning: 'settings', ids: ['settings'] },
    { name: 'help', letter: '?', meaning: 'help', ids: ['help'] },
    { name: 'search', letter: '/', meaning: 'search', ids: ['search'] },
    { name: 'extend-row', letter: '+', meaning: 'extend a row', ids: ['extend-row'], shares: 'extend is the widget menu, add members the row and heading menus' },
    { name: 'peek-0', letter: '0', meaning: 'peek zoom 0 (the war room wall)', ids: ['peek:0'], shares: 'the war room widget menu only' },
    { name: 'peek-25', letter: '2', meaning: 'peek zoom 25 (the war room wall)', ids: ['peek:25'], shares: 'the war room widget menu only, an ordered set of digits' },
    { name: 'peek-50', letter: '5', meaning: 'peek zoom 50 (the war room wall)', ids: ['peek:50'], shares: 'the war room widget menu only' },
    { name: 'peek-75', letter: '7', meaning: 'peek zoom 75 (the war room wall)', ids: ['peek:75'], shares: 'the war room widget menu only' },
    { name: 'peek-100', letter: '1', meaning: 'peek zoom 100 (the war room wall)', ids: ['peek:100'], shares: 'the war room widget menu only; compact below is the bar size menu' },
    { name: 'compact', letter: '1', meaning: 'compact, area closed', ids: ['bar-size-compact', 'area-closed', 'density-compact'], shares: 'compact is the bar size, area and density menus; peek zoom 100 is the war room widget menu only' },
    { name: 'cozy', letter: '2', meaning: 'cozy, area glance', ids: ['bar-size-cozy', 'area-glance', 'density-cozy'], shares: 'cozy is the bar size, area and density menus; peek zoom 25 is the war room widget menu only' },
    { name: 'detailed', letter: '3', meaning: 'detailed, area full', ids: ['bar-size-detailed', 'area-full', 'density-detailed'] },
]);

const BY_ID = Object.freeze(
    Object.fromEntries(LETTERS.flatMap((entry) => entry.ids.map((id) => [id, entry.letter]))),
);

const BY_VERB = Object.freeze(
    Object.fromEntries(LETTERS.flatMap((entry) => (entry.verbs ?? []).map((verb) => [verb, entry.letter]))),
);

const KEYABLE = /[a-z0-9]/;
const FALLBACK = 'abcdefghijklmnopqrstuvwxyz0123456789';

const RESERVED = new Set([BY_VERB.delete, BY_VERB.archive, BY_ID.close]);


export function registeredKey(id) {
    if (!id) return null;
    return BY_ID[id] ?? BY_VERB[id.split('-')[0] ?? ''] ?? null;
}

export function assignMenuKeys(items) {
    const used = new Set();
    const out = items.map((item) => {
        const want = item.skip ? null : registeredKey(item.id);
        if (!want || used.has(want)) return '';
        used.add(want);
        return want;
    });
    items.forEach((item, at) => {
        if (out[at] || item.skip) return;
        const pool = [...([...String(item.label).toLowerCase()].filter((ch) => KEYABLE.test(ch)).join('') + FALLBACK)];
        const free = pool.find((ch) => !used.has(ch) && !RESERVED.has(ch)) ?? pool.find((ch) => !used.has(ch));
        if (!free) return;
        used.add(free);
        out[at] = free;
    });
    return out;
}
