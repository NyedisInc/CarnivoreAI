/*  hidden  */

console.log('[TerminalToolsMenu Module] Loading...');

(function () {
    'use strict';

    var ENTRY_IDS = [
        'toolAttachImage',
        'toolPasteClipboard',
        'toolCopyOutput'
    ];

    function createTerminalToolsMenu(deps) {
        var wiring = deps || {};

        var termWrapper = null;

        /*  hidden  */
        var fileInputEl = null;

        var ICONS = {
            copy:
                '<rect x="5.5" y="5.5" width="8" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/>' +
                '<path d="M10.5 3.5v-1a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
            paste:
                '<path d="M4.5 3.5h-1a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1h-1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
                '<rect x="5.5" y="1.5" width="5" height="3" rx="1" stroke="currentColor" stroke-width="1.5"/>',
            image:
                '<rect x="2" y="3.5" width="12" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/>' +
                '<path d="m3 11 3-3 2.5 2.5L11 8l2 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
                '<circle cx="6" cy="6.5" r="1" stroke="currentColor" stroke-width="1.5"/>'
        };

        function buildIcon(name) {
            return window.FabMenu ? window.FabMenu.buildIcon(ICONS, name) : null;
        }

        var menu = window.FabMenu.create({
            menuId: wiring.menuId || 'terminalToolsMenu',
            menuClass: 'terminal-tools-menu',
            ariaLabel: 'terminal tools',
            rows: buildItems
        });

        function buildItems(ctl) {
            var c = ctl || menu;
            return [
                c.item(ENTRY_IDS[0], buildIcon('image'), 'attach file', function () {
                    if (fileInputEl) fileInputEl.click();
                }),
                c.item(ENTRY_IDS[1], buildIcon('paste'), 'paste from clipboard', function () {
                    if (window.ClipboardTools) {
                        window.ClipboardTools.pasteFromClipboard(termWrapper);
                    }
                }),
                c.item(ENTRY_IDS[2], buildIcon('copy'), 'copy output', function () {
                    if (window.CopyOutput) window.CopyOutput.open(termWrapper);
                })
            ];
        }

        /*  hidden  */
        function wire(wrapper, input) {
            termWrapper = wrapper;
            fileInputEl = input || fileInputEl;
        }

        return {
            wire: wire,
            toggle: menu.toggle,
            open: menu.open,
            close: menu.close,
            isOpen: menu.isOpen,
            buildItems: buildItems,
            ENTRY_IDS: ENTRY_IDS,
            ICONS: ICONS
        };
    }

    /* the page terminal */
    var defaultInstance = createTerminalToolsMenu();

    window.TerminalToolsMenu = Object.assign(
        { create: createTerminalToolsMenu }, defaultInstance);
})();

console.log('[TerminalToolsMenu Module] Exported as window.TerminalToolsMenu');
