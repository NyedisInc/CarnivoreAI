/* position: fixed z-index: 70 */

console.log('[FabMenu Module] Loading...');

(function () {
    'use strict';

    var NOTICE_Z = 10005;

    var NOTICE_MS = { error: 5000, info: 3000, success: 3000 };

    var noticeEl = null;

    var noticeTimer = null;

    function notify(message, kind) {
        if (!message) return null;
        var level = NOTICE_MS[kind] ? kind : 'info';

        if (!noticeEl || !noticeEl.parentNode) {
            noticeEl = document.createElement('div');
            noticeEl.setAttribute('id', 'fabMenuNotice');
            noticeEl.className = 'fab-menu-notice';
            noticeEl.setAttribute('role', 'status');
            noticeEl.setAttribute('aria-live', 'polite');
            document.body.appendChild(noticeEl);
        }
        noticeEl.style.zIndex = String(NOTICE_Z);
        noticeEl.textContent = message;
        noticeEl.setAttribute('data-kind', level);
        noticeEl.classList.add('visible');

        if (noticeTimer) clearTimeout(noticeTimer);
        noticeTimer = setTimeout(function () {
            noticeTimer = null;
            if (noticeEl) noticeEl.classList.remove('visible');
        }, NOTICE_MS[level]);
        return noticeEl;
    }

    function dismissNotice() {
        if (noticeTimer) {
            clearTimeout(noticeTimer);
            noticeTimer = null;
        }
        if (noticeEl) noticeEl.classList.remove('visible');
    }

    function buildIcon(icons, name) {
        var body = icons ? icons[name] : null;
        if (!body) return null;
        if (typeof document.createElementNS !== 'function') return null;
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '16');
        svg.setAttribute('height', '16');
        svg.setAttribute('viewBox', '0 0 16 16');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('aria-hidden', 'true');
        svg.innerHTML = body;
        return svg;
    }

    function buildRow(spec) {
        var item = document.createElement('button');
        item.type = 'button';
        item.setAttribute('id', spec.id);
        item.className = 'fab-menu__item';
        item.setAttribute('role', 'menuitem');

        if (spec.icon) item.appendChild(spec.icon);

        var text = document.createElement('span');
        text.className = 'fab-menu__label';
        text.textContent = spec.label;
        item.appendChild(text);

        item.addEventListener('click', function (e) {
            e.stopPropagation();
            spec.close();
            spec.onPick(notify);
        });
        return item;
    }

    function create(config) {
        var menuEl = null;

        var triggerEl = null;

        var onDocPointer = null;
        var onDocKey = null;

        function isOpen() {
            return menuEl !== null;
        }

        function close() {
            if (onDocPointer) {
                document.removeEventListener('pointerdown', onDocPointer, true);
                onDocPointer = null;
            }
            if (onDocKey) {
                document.removeEventListener('keydown', onDocKey, true);
                onDocKey = null;
            }
            if (menuEl) {
                menuEl.remove();
                menuEl = null;
            }
            if (triggerEl) triggerEl.setAttribute('aria-expanded', 'false');
        }

        function item(id, icon, label, onPick) {
            return buildRow({
                id: id, icon: icon, label: label, onPick: onPick, close: close
            });
        }

        function open() {
            close();
            if (!triggerEl) return;

            menuEl = document.createElement('div');
            menuEl.className = 'fab-menu popup-focus ' + config.menuClass;
            menuEl.setAttribute('id', config.menuId);
            menuEl.setAttribute('role', 'menu');
            menuEl.setAttribute('aria-label', config.ariaLabel);
            config.rows(controller).forEach(function (r) {
                menuEl.appendChild(r);
            });

            document.body.appendChild(menuEl);
            if (window.AnchorPopover) window.AnchorPopover.place(menuEl, triggerEl);
            triggerEl.setAttribute('aria-expanded', 'true');

            onDocPointer = function (e) {
                if (!menuEl) return;
                if (menuEl.contains(e.target)) return;
                if (triggerEl && triggerEl.contains(e.target)) return;
                close();
            };
            onDocKey = function (e) {
                if (e.key === 'Escape') close();
            };
            setTimeout(function () {
                document.addEventListener('pointerdown', onDocPointer, true);
                document.addEventListener('keydown', onDocKey, true);
            }, 0);
        }

        function toggle(btn) {
            if (btn && btn !== triggerEl) {
                if (triggerEl) triggerEl.setAttribute('aria-expanded', 'false');
                triggerEl = btn;
            }
            if (isOpen()) {
                close();
            } else {
                open();
            }
        }

        function wire(btn) {
            if (!btn) return;
            triggerEl = btn;
            if (btn._fabMenuWired) return;
            btn._fabMenuWired = true;
            btn.setAttribute('aria-expanded', 'false');
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                toggle(null);
            });
        }

        function trigger() {
            return triggerEl;
        }

        var controller = {
            open: open,
            close: close,
            isOpen: isOpen,
            wire: wire,
            toggle: toggle,
            item: item,
            trigger: trigger,
            notify: notify
        };
        return controller;
    }

    window.FabMenu = {
        create: create,
        buildIcon: buildIcon,
        notify: notify,
        dismissNotice: dismissNotice,
        NOTICE_Z: NOTICE_Z
    };
})();

console.log('[FabMenu Module] Exported as window.FabMenu');
