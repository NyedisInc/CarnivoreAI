/* could not be read */

console.log('[SessionModelIcon Module] Loading...');

(function () {
    'use strict';

    var ROBOT = '<rect x="3.5" y="5" width="13" height="10.5" rx="2.6" '
        + 'stroke="currentColor" stroke-width="1.5"/>'
        + '<path d="M10 2.6v2.4M2.6 9.2v2.6M17.4 9.2v2.6" stroke="currentColor" '
        + 'stroke-width="1.5" stroke-linecap="round"/>'
        + '<circle cx="10" cy="2" r="1.05" fill="currentColor"/>'
        + '<circle cx="7.4" cy="9.4" r="1.15" fill="currentColor"/>'
        + '<circle cx="12.6" cy="9.4" r="1.15" fill="currentColor"/>'
        + '<path d="M7.6 12.6h4.8" stroke="currentColor" stroke-width="1.5" '
        + 'stroke-linecap="round"/>'
        + '<rect x="7.5" y="2.5" width="5" height="3" rx="1" stroke="currentColor" '
        + 'stroke-width="1.5"/>';

    var TOP_TIER = 5;

    /* reads as broken */
    var TOP_EFFORTS = ['xhigh', 'max'];

    var SHIMMER_EFFORTS = ['xhigh', 'max', 'ultracode'];
    var SHEEN_EFFORTS = ['high', 'xhigh'];

    function isTopped(tier, effort) {
        if (tier !== TOP_TIER) return false;
        if (typeof effort !== 'string') return false;
        return TOP_EFFORTS.indexOf(effort.trim().toLowerCase()) !== -1;
    }

    function tierAttr(tier) {
        if (typeof tier !== 'number' || !isFinite(tier)) return '';
        if (!Number.isInteger(tier)) return '';
        return (tier >= 1 && tier <= TOP_TIER) ? String(tier) : '';
    }

    /* could not be read */
    function html(model, tier, effort, esc) {
        if (typeof model !== 'string' || !model.trim()) return '';
        var safe = (typeof esc === 'function') ? esc : function (v) {
            return String(v == null ? '' : v)
                .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        };
        var topped = isTopped(tier, effort);
        var shimmer = (window.EffortLevel && SHIMMER_EFFORTS.indexOf(
            window.EffortLevel.level(effort)) !== -1)
            ? ' ' + window.EffortLevel.className(effort) : '';
        var sheen = shimmer && SHEEN_EFFORTS.indexOf(window.EffortLevel.level(effort)) !== -1;
        var label = model.trim() + (effort ? ' at ' + effort : '');
        var attrs = ' data-model-tier="' + safe(tierAttr(tier)) + '"';
        if (topped) attrs += ' data-model-top="1"';
        return (topped ? '<span class="session-sidebar-row-model-wrap">' : '')
            + '<span class="session-sidebar-row-model' + shimmer + '"' + attrs
            + ' role="img" aria-label="' + safe(label) + '"'
            + ' title="' + safe(label) + '">'
            + '<svg width="14" height="14" viewBox="0 0 20 20" fill="none" '
            + 'aria-hidden="true">' + ROBOT + '</svg>'
            + (sheen ? '<span class="effort-fx" data-anim-host aria-hidden="true"><i></i><i></i><i></i></span>' : '')
            + '</span>'
            + (topped ? '<span class="session-sidebar-row-model__spark" aria-hidden="true"></span></span>' : '');
    }

    window.SessionModelIcon = {
        html: html,
        isTopped: isTopped,
        tierAttr: tierAttr,
        TOP_TIER: TOP_TIER,
        TOP_EFFORTS: TOP_EFFORTS,
        ROBOT: ROBOT,
    };
})();

console.log('[SessionModelIcon Module] Exported as window.SessionModelIcon');
