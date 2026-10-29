(function () {
    'use strict';

    var COST_TIER_THRESHOLDS = [2, 8, 16, 32];

    var TIER_COLOURS = ['green', 'blue', 'yellow', 'orange', 'red'];

    var LIGHTS = [
        { inner: 'waiting-permission', outer: 'active', text: 'stopped, waiting on you: a permission question, or a prompt at startup' },
        { inner: 'notice', outer: 'active', text: 'still working, and wants your attention' },
        { inner: 'working', outer: 'active', text: 'working. a light that moves is a session that is moving' },
        { inner: 'done', outer: 'unread', text: 'finished a turn you have not looked at yet' },
        { inner: 'idle', outer: 'steady', text: 'idle, already read' },
        { inner: 'dead', outer: 'off', text: 'dead (the process exited) or disconnected (no live connection)' },
        { inner: 'unknown', outer: 'dim', text: 'not measured: nothing has reported in, which is not the same as idle' },
    ];

    var HEADER_NOTE = 'a group header shows one light for everything inside it: '
        + 'the state in that group that most wants you.';

    var overlayEl = null;
    var returnFocus = null;

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function tierRange(tier) {
        var t = COST_TIER_THRESHOLDS;
        if (tier <= 1) return 'under $' + t[0];
        if (tier > t.length) return '$' + t[t.length - 1] + ' and up';
        return '$' + t[tier - 2] + ' to under $' + t[tier - 1];
    }

    function robotRows() {
        var icon = window.SessionModelIcon;
        var rows = [];
        for (var tier = 1; tier <= COST_TIER_THRESHOLDS.length + 1; tier++) {
            rows.push({
                html: icon ? icon.html('tier ' + tier, tier, null) : '',
                text: 'tier ' + tier + ', ' + TIER_COLOURS[tier - 1] + ': ' + tierRange(tier)
                    + ' per million output tokens',
            });
        }
        var top = icon ? icon.TOP_EFFORTS.join(' or ') : 'xhigh or max';
        rows.push({
            html: icon ? icon.html('top tier at top effort', icon.TOP_TIER, icon.TOP_EFFORTS[0]) : '',
            text: 'purple with a sparkle: the top tier running at ' + top + ' effort',
        });
        rows.push({
            html: icon ? icon.html('model not priced', null, null) : '',
            text: 'muted: the model is not known, or has no price on record',
        });
        return rows;
    }

    function providerRows() {
        var icon = window.AgentFamilyIcon;
        if (!icon) return [];
        return icon.FAMILIES.map(function (family) {
            return {
                html: '<span class="session-sidebar-row-provider" data-agent-family="' + esc(family) + '" '
                    + 'aria-hidden="true">' + icon.svg(family) + '</span>',
                text: icon.labelFor(family),
            };
        });
    }

    function markRows() {
        var controls = window.SessionSidebarRowControls;
        var rows = [];
        if (controls && typeof controls.pinLegendHtml === 'function') {
            rows.push({ html: controls.pinLegendHtml(true), text: 'pinned: kept at the top of the list' });
            rows.push({ html: controls.pinLegendHtml(false), text: 'not pinned (tilted). click it to pin' });
        }
        var glyphs = globalThis.CloudeGlyphs;
        if (glyphs && typeof glyphs.glyphSvg === 'function') {
            rows.push({
                html: '<span class="sidebar-help__glyph" aria-hidden="true">' + glyphs.glyphSvg('telescope') + '</span>',
                text: 'shared: a read-only link to this session is live',
            });
        }
        return rows;
    }

    function listHtml(rows) {
        return '<ul class="sidebar-help__list">' + rows.map(function (r) {
            return '<li class="sidebar-help__item"><span class="sidebar-help__swatch">' + r.html + '</span>'
                + '<span class="sidebar-help__text">' + esc(r.text) + '</span></li>';
        }).join('') + '</ul>';
    }

    function t(key) {
        return (window.CloudeI18n && typeof window.CloudeI18n.t === 'function') ? window.CloudeI18n.t(key) : key;
    }

    function panelHtml() {
        var led = window.StatusLed;
        var lights = LIGHTS.map(function (l) {
            return { html: led ? led.ledHtml({ inner: l.inner, outer: l.outer }) : '', text: l.text };
        });
        var marksBody = '<h4 class="sidebar-help__subh">status lights</h4>' + listHtml(lights)
            + '<p class="sidebar-help__note">' + esc(HEADER_NOTE) + '</p>'
            + '<h4 class="sidebar-help__subh">model robot: what the model costs</h4>' + listHtml(robotRows())
            + '<h4 class="sidebar-help__subh">provider mark: which agent it is</h4>' + listHtml(providerRows())
            + '<h4 class="sidebar-help__subh">other marks</h4>' + listHtml(markRows());
        return '<div class="modal-content sidebar-help__content" role="dialog" aria-modal="true" '
            + 'aria-labelledby="sidebar-help-title">'
            + '<div class="modal-header sidebar-help__header">'
            + '<span id="sidebar-help-title">help</span>'
            + '<button type="button" class="modal-close" id="sidebar-help-header-close" '
            + 'aria-label="' + esc(t('sidebar_help.close')) + '">&times;</button>'
            + '</div>'
            + '<div class="sidebar-help__nav" role="tablist" aria-label="help sections">'
            + navButtonHtml('marks', 'marks') + navButtonHtml('releases', 'releases') + navButtonHtml('features', 'features')
            + '</div>'
            + '<div class="sidebar-help__scroll">'
            + '<section class="sidebar-help__section" id="sidebar-help-section-marks">'
            + '<button type="button" class="sidebar-help__collapse-trigger" id="sidebar-help-marks-toggle" '
            + 'aria-expanded="false" aria-controls="sidebar-help-marks-body">'
            + '<span class="sidebar-help__collapse-caret" aria-hidden="true"></span>'
            + '<span class="sidebar-help__collapse-label">what the marks mean</span>'
            + '</button>'
            + '<div class="sidebar-help__collapse-body" id="sidebar-help-marks-body" hidden>' + marksBody + '</div>'
            + '</section>'
            + '<section class="sidebar-help__section" id="sidebar-help-section-releases">'
            + '<div id="sidebar-help-releases"></div>'
            + '</section>'
            + '<section class="sidebar-help__section" id="sidebar-help-section-features">'
            + '<div id="sidebar-help-features"></div>'
            + '</section>'
            + '</div>'
            + '<div class="modal-footer sidebar-help__footer">'
            + '<button type="button" class="modal-btn modal-btn-secondary" id="sidebar-help-close">close</button>'
            + '</div></div>';
    }

    function navButtonHtml(target, label) {
        return '<button type="button" class="sidebar-help__nav-btn" data-help-nav="' + esc(target) + '">'
            + esc(label) + '</button>';
    }

    function scrollToSection(target) {
        if (!overlayEl) return;
        if (target === 'marks') {
            var trigger = overlayEl.querySelector('#sidebar-help-marks-toggle');
            var body = overlayEl.querySelector('#sidebar-help-marks-body');
            if (trigger && body && trigger.getAttribute('aria-expanded') !== 'true') {
                trigger.setAttribute('aria-expanded', 'true');
                body.hidden = false;
            }
        }
        var sectionId = 'sidebar-help-section-' + target;
        var selector = '#' + sectionId;
        var section = overlayEl.querySelector(selector);
        if (section) section.scrollIntoView({ block: 'start' });
    }

    function toggleMarks() {
        if (!overlayEl) return;
        var trigger = overlayEl.querySelector('#sidebar-help-marks-toggle');
        var body = overlayEl.querySelector('#sidebar-help-marks-body');
        if (!trigger || !body) return;
        var expanded = trigger.getAttribute('aria-expanded') === 'true';
        trigger.setAttribute('aria-expanded', expanded ? 'false' : 'true');
        body.hidden = expanded;
    }

    function focusableElements() {
        if (!overlayEl) return [];
        var selector = 'a[href], button:not([disabled]), input:not([disabled]), '
            + 'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
        var found = overlayEl.querySelectorAll(selector);
        return Array.prototype.filter.call(found, function (el) {
            return el.offsetParent !== null || el === document.activeElement;
        });
    }

    function trapTab(e) {
        var focusables = focusableElements();
        if (focusables.length === 0) return;
        var first = focusables[0];
        var last = focusables[focusables.length - 1];
        var active = document.activeElement;
        var inside = overlayEl.contains(active);
        if (e.shiftKey) {
            if (!inside || active === first) {
                e.preventDefault();
                last.focus();
            }
        } else if (!inside || active === last) {
            e.preventDefault();
            first.focus();
        }
    }

    function onKey(e) {
        if (e.key === 'Escape') {
            if (overlayEl && overlayEl.querySelector('.sidebar-help__lightbox')) return;
            e.preventDefault();
            e.stopImmediatePropagation();
            close();
            return;
        }
        if (e.key === 'Tab' && overlayEl) {
            trapTab(e);
        }
    }

    function close() {
        if (window.CloudeWeb && typeof window.CloudeWeb.unmountHelpFeatures === 'function') {
            window.CloudeWeb.unmountHelpFeatures();
        }
        if (window.CloudeWeb && typeof window.CloudeWeb.unmountHelpReleases === 'function') {
            window.CloudeWeb.unmountHelpReleases();
        }
        if (overlayEl && overlayEl.parentNode) overlayEl.parentNode.removeChild(overlayEl);
        overlayEl = null;
        document.removeEventListener('keydown', onKey, true);
        if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
        returnFocus = null;
    }

    function open(anchor) {
        if (overlayEl) return;
        returnFocus = anchor || document.activeElement;
        var overlay = document.createElement('div');
        overlay.className = 'modal-overlay sidebar-help';
        overlay.innerHTML = panelHtml();
        overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
        document.body.appendChild(overlay);
        overlayEl = overlay;
        overlay.querySelector('#sidebar-help-close').addEventListener('click', close);
        overlay.querySelector('#sidebar-help-header-close').addEventListener('click', close);
        overlay.querySelector('#sidebar-help-marks-toggle').addEventListener('click', toggleMarks);
        var navButtons = overlay.querySelectorAll('[data-help-nav]');
        for (var i = 0; i < navButtons.length; i++) {
            navButtons[i].addEventListener('click', function (e) {
                scrollToSection(e.currentTarget.getAttribute('data-help-nav'));
            });
        }
        document.addEventListener('keydown', onKey, true);
        overlay.querySelector('#sidebar-help-close').focus();
        if (window.CloudeWeb && typeof window.CloudeWeb.mountHelpFeatures === 'function') {
            window.CloudeWeb.mountHelpFeatures();
        }
        if (window.CloudeWeb && typeof window.CloudeWeb.mountHelpReleases === 'function') {
            window.CloudeWeb.mountHelpReleases();
        }
    }

    function isOpen() { return !!overlayEl; }

    var exported = {
        open: open, close: close, isOpen: isOpen, panelHtml: panelHtml, tierRange: tierRange,
        scrollToSection: scrollToSection,
        LIGHTS: LIGHTS, COST_TIER_THRESHOLDS: COST_TIER_THRESHOLDS,
    };
    if (typeof window !== 'undefined') window.SidebarHelp = exported;
    if (typeof globalThis !== 'undefined') globalThis.SidebarHelp = exported;
})();
