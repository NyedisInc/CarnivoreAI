
const WIDGET = ['web/src/lib/widget-menu/model.ts', 'web/src/lib/widget-menu/bar-menu.ts', 'web/src/lib/widget-menu/rail-menu.ts'];

export const MENU_GROUPS = Object.freeze([
    {
        id: 'sidebar',
        menus: [
            { id: 'agent-row', files: ['web/src/lib/item-menu/menus/row-items.ts', 'web/src/lib/item-menu/menus/row.ts', 'web/src/cplugs/unread/index.ts', 'web/src/cplugs/share/index.ts', 'web/src/cplugs/huddle/session-roles-action.ts'],
              items: ['new-in-folder', 'new-terminal-here', 'fork', 'rename', 'pin', 'add-to', 'show-path', 'copy-session-id', 'schedule', 'keep-awake', 'mute', 'restart',
                  'sleep', 'send-to', 'move-to-folder', 'close', 'share-read-only', 'huddle-project-lead', 'mark-read', 'mark-unread', 'wake', 'archive', 'update-restart', 'reconnect-mcp', 'remove-from-group'] },
            { id: 'browser-row', files: ['web/src/lib/item-menu/menus/row.ts', 'web/src/lib/item-menu/menus/row-items.ts'], items: ['popout', 'rename', 'pin', 'move-to-group', 'download', 'close', 'remove-from-group'] },
            { id: 'page-row', files: ['web/src/lib/item-menu/menus/page-actions.ts', 'web/src/lib/item-menu/menus/row-items.ts', 'web/src/lib/item-menu/menus/row.ts', 'web/src/cplugs/publicboard/page-row-action.ts'], items: ['popout', 'rename', 'pin', 'move-to-group', 'close', 'share-link'] },
            { id: 'project-heading', files: ['web/src/lib/item-menu/menus/fold-inside.ts', 'web/src/lib/item-menu/menus/project.ts', 'web/src/lib/projects-shared/ledger-model.ts'], items: ['new-agent', 'load-blueprint', 'rename-project', 'add-to-company', 'show-path', 'fold-inside', 'sleep', 'archive-project', 'remove-from-company'] },
            { id: 'company-heading', files: ['web/src/lib/item-menu/menus/fold-inside.ts', 'web/src/lib/item-menu/menus/company.ts'], items: ['rename-company', 'clear-company-color', 'fold-inside', 'delete-company'] },
            { id: 'group-heading', files: ['web/src/lib/item-menu/menus/fold-inside.ts', 'web/src/lib/item-menu/menus/group.ts'], items: [{ branch: 'customize', items: ['rename-group', 'add-members', 'colour', 'group-icon', 'group-rule'] }, 'fold-inside', 'sleep', 'move-up', 'move-down', 'delete-group'] },
            { id: 'section-heading', files: ['web/src/lib/item-menu/menus/fold-inside.ts', 'web/src/lib/item-menu/menus/section.ts'], items: ['fold', 'fold-inside', 'move-up', 'move-down', 'browser', 'edit-layout', 'done-editing'] },
            { id: 'color-menu', files: ['web/src/lib/item-menu/menus/color.ts', 'web/src/lib/projects-shared/ledger-model.ts'], items: ['color-style', 'pick-color'] },
            { id: 'leader', files: ['web/src/lib/item-menu/menus/leader.ts'], items: ['wake', 'rename-agent', 'turn-off-agent'] },
            { id: 'new-menu', files: ['web/src/lib/drawer-tabs/NewSessionButton.svelte', 'web/src/lib/drawer-tabs/drawer-tabs.ts'], items: ['agent', 'terminal', 'browser', 'project', 'group'] },
            { id: 'view-menu', files: ['web/src/lib/session-list/view-choices.ts'],
              items: ['density-compact', 'density-cozy', 'density-detailed', 'show-leaders', 'show-archived', 'show-stats'] },
            { id: 'account-menu', files: ['web/src/lib/drawer-hud/AccountMenu.svelte', 'web/src/lib/drawer/bar.ts'], items: ['account_page', 'layout', 'master_all', 'signout', 'logout', 'signin'] },
            { id: 'rail-menu', files: ['web/src/lib/widget-menu/rail-menu.ts'], items: ['pin-bar', 'open-drawer', 'close-tab'] },
        ],
    },
    {
        id: 'widgets',
        menus: [
            { id: 'widget-menu', files: [...WIDGET, 'web/src/lib/item-menu/menus/widget.ts', 'web/src/opscenter/widgets/menu/header-actions.ts', 'web/src/lib/widget-menu/declared-nodes.ts'],
              items: ['close-widget', 'remove-widget', 'sort:name', 'sort:recent', 'sort:project', 'sort:activity', 'sort:last_used', 'pop-out', 'show-header', 'settings',
                  'focus-main-window', 'extend-row', 'pull-back-row', 'widget-move-up', 'widget-move-down', 'move-to-drawer', 'move-to-bar', 'done-editing', 'edit-layout', 'close-tab'] },
            { id: 'layout-editor', files: ['web/src/opscenter/layout-editor/empty-space-menu.svelte.ts'], items: ['toggle-edit-layout'] },
            { id: 'bar-menu', files: ['web/src/lib/widget-menu/bar-menu.ts'], items: ['bar-size-compact', 'bar-size-cozy', 'bar-size-detailed', 'area-closed', 'area-glance', 'area-full', 'pin-bar'] },
            { id: 'files', files: ['web/src/opscenter/cells/files/Cell.svelte', 'web/src/opscenter/cells/files/state.ts'],
              items: ['open-path', 'git-ignored-files', 'collapse-all', 'list-project-first', 'include-dot-files', 'just-changes', 'whole-file', 'show-global-folder', 'reload'] },
            { id: 'timeline', files: ['web/src/opscenter/cells/timeline/Cell.svelte', 'web/src/opscenter/cells/timeline/actions.svelte.ts'],
              items: ['show-restores', 'show-restarts', 'show-bookmarks', 'show-compacts', 'show-sleeping', 'open-conversation', 'rewind-here', 'open-copy', 'squeeze-sleeps', 'bookmark'] },
            { id: 'war-room', files: ['web/src/opscenter/cells/warroom/Cell.svelte', 'web/src/opscenter/cells/warroom/state.ts'],
              items: ['show-computers', 'show-browsers', 'show-shells', 'show-sleeping', 'peek:0', 'peek:25', 'peek:50', 'peek:75', 'peek:100'] },
            { id: 'crosstalk', files: ['web/src/opscenter/cells/crosstalk/Cell.svelte'], items: ['close-thread', 'scope:all', 'scope:project', 'scope:session', 'mark-all-read'] },
            { id: 'notes', files: ['web/src/opscenter/cells/notes/Cell.svelte'], items: ['mode:edit', 'mode:preview', 'save'] },
            { id: 'task-manager', files: ['web/src/opscenter/cells/task-manager-mk2/mk2-menu.svelte.ts', 'web/src/opscenter/cells/task-manager-mk2/Mk2Discussion.svelte'],
              items: ['show-counts', 'project-colors', 'group-by-area', 'accordion', 'show-completed', 'status-bar', 'help'] },
            { id: 'terminal', files: ['web/src/opscenter/cells/terminal-live/terminal-menu-actions.ts', 'web/src/opscenter/cells/terminal-live/toolbar.ts'], items: ['open-in-terminal', 'zoom', 'background', 'search'] },
            { id: 'swarm-node', files: ['web/src/cplugs/huddle/swarm/node-menu.ts', 'web/src/lib/projects-shared/ledger-model.ts'], items: ['color', 'shape', 'set-image', 'remove-image'] },
            { id: 'projects-page', files: ['web/src/lib/projects-shared/ledger-model.ts', 'web/src/lib/drawer/layouts-menu.ts'],
              items: ['pick-color', 'regenerate-art', 'turn-on-agent', 'copy-path', 'save-blueprint', 'set-image', 'remove-image'] },
        ],
    },
]);

export const UNDRAWN_ITEM_IDS = Object.freeze(['new-session', 'change-agent-type', 'edit-rail-icons', 'done-rail-icons', 'crosstalk', 'messaging', 'show-open']);

export function flatItemIds(items) {
    return items.flatMap((item) => (typeof item === 'string' ? [item] : [item.branch, ...flatItemIds(item.items)]));
}
