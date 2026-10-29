/* could not be determined */

console.log('[SessionStatusUI Module] Loading...');

(function () {
    const STATUS_LABELS = {
        dead: 'dead - process exited',
        question: 'your turn - the agent needs your permission',
        notice: 'your turn - the agent wants your attention',
        working_subagent: 'working - a subagent is active',
        working: 'working',
        finished_unread: 'done - unread',
        idle: 'idle - read, nothing running',
        stopped: 'ended - the session is no longer running',
        asleep: 'asleep - stopped to free memory, wake it from the session menu',
        unknown: 'not measured',
        running: 'working',
    };

    const ASLEEP_UNREAD_LABEL = 'asleep, flagged unread - wake it to follow up';

    const SOURCE_SUFFIX = {
        registry: "via the agent's own session record",
        pane: 'via the pane',
        transcript: 'via transcript',
        seed_row: 'via the session record',
        tmux: 'via tmux',
        // server stopped
        hook: 'via hooks',
    };

    /* no string layer */
    const ACTIVITY_HINT_SUFFIX = {
        shell: 'shell still running',
        codex_interrupted: 'interrupted, at the prompt',
        codex_turn_failed: 'last turn failed',
    };

    function questionLabel(status, activityHint) {
        if (normalizeStatus(status) !== 'question' || typeof activityHint !== 'string') return '';
        if (activityHint === 'question') return 'your turn - question waiting';
        const m = /^question:(\d+)\/(\d+)$/.exec(activityHint);
        return m ? `your turn - question ${m[1]} of ${m[2]} waiting` : '';
    }

    function labelWithSource(status, statusSource, activityHint, parkedSummary) {
        const label = questionLabel(status, activityHint)
            || STATUS_LABELS[normalizeStatus(status)];
        const suffix = Object.prototype.hasOwnProperty.call(
            SOURCE_SUFFIX, statusSource,
        ) ? SOURCE_SUFFIX[statusSource] : '';
        const hint = Object.prototype.hasOwnProperty.call(
            ACTIVITY_HINT_SUFFIX, activityHint,
        ) ? ACTIVITY_HINT_SUFFIX[activityHint] : '';
        const head = suffix ? `${label} (${suffix})` : label;
        const withHint = hint ? `${head}, ${hint}` : head;
        return typeof parkedSummary === 'string' && parkedSummary
            ? `${withHint} - ${parkedSummary}`
            : withHint;
    }

    const STATUS_DOT_CLASS = {
        dead: 'dead',
        question: 'question',
        notice: 'notice',
        working_subagent: 'working-subagent',
        working: 'working',
        finished_unread: 'finished-unread',
        idle: 'idle',
        stopped: 'stopped',
        asleep: 'asleep',
        unknown: 'unknown',
        running: 'working',
    };

    function escapeAttr(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function normalizeStatus(status) {
        return Object.prototype.hasOwnProperty.call(STATUS_LABELS, status)
            ? status
            : 'unknown';
    }

    /* aria-label="dead - process exited" title="dead - process exited" */
    function dotHtml(status, signals) {
        const key = normalizeStatus(status);
        const hostOff = (signals || {}).host_offline;
        const label = key === 'asleep' && (signals || {}).unread
            ? ASLEEP_UNREAD_LABEL
            : hostOff && key !== 'asleep'
            ? `${hostOff} offline`
            : (signals || {}).usage_limit && key !== 'asleep' && key !== 'dead' && key !== 'stopped'
            ? (signals || {}).usage_limit
            : labelWithSource(
                key,
                (signals || {}).status_source,
                (signals || {}).activity_hint,
                (signals || {}).parked_summary,
            );
        const cssClass = STATUS_DOT_CLASS[key];

        if (globalThis.StatusLed) {
            const s = signals || {};
            const led = globalThis.StatusLed.ledStateFor({
                activity_status: key,
                unread: s.unread,
                startup_gate: s.startup_gate,
                transport: s.transport,
                host_offline: s.host_offline,
                usage_limit: s.usage_limit,
            });
            return globalThis.StatusLed.ledHtml({
                inner: led.inner,
                outer: led.outer,
                size: s.size,
                title: label,
                extraClass: `status-dot status-dot--${cssClass}`,
            });
        }
        return (
            `<span class="status-dot status-dot--${escapeAttr(cssClass)}" role="img" ` +
            `title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}"></span>`
        );
    }

    function labelFor(status) {
        return STATUS_LABELS[normalizeStatus(status)];
    }

    /* role="button" */
    function markUnreadHtml(tmuxName, unread) {
        if (globalThis.UIFlags && !globalThis.UIFlags.showMarkUnreadControl()) {
            return '';
        }
        const label = unread
            ? 'clear unread'
            : 'mark unread';
        const pressed = unread ? 'true' : 'false';
        const safeName = escapeAttr(tmuxName);
        return (
            `<span class="mark-unread-toggle${unread ? ' mark-unread-toggle--active' : ''}" ` +
            `role="button" tabindex="0" aria-pressed="${pressed}" ` +
            `title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}" ` +
            `data-mark-unread="${safeName}" data-unread-current="${pressed}">` +
            `${unread ? envelopeFilledSvg() : envelopeOutlineSvg()}</span>`
        );
    }

    /* <svg width="16" height="16" */
    function envelopeOutlineSvg() {
        return glyph('envelope-outline');
    }

    /* <svg width="16" height="16" */
    function envelopeFilledSvg() {
        return glyph('envelope-filled');
    }

    /* <svg width="16" height="16" */
    function trashIconSvg() {
        return glyph('trash');
    }

    /* <svg width="16" height="16" */
    function closeIconSvg() {
        return glyph('close');
    }

    /* <svg width="16" height="16" */
    function restartIconSvg() {
        return glyph('restart');
    }

    /* <svg width="16" height="16" */
    function pencilIconSvg() {
        return glyph('pencil');
    }

    /* <svg width="16" height="16" */
    function folderIconSvg() {
        return (
            '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
            '<path d="M2 4.25C2 3.69772 2.44772 3.25 3 3.25H6.5L7.75 4.75H13C13.5523 4.75 14 5.19772 14 5.75V11.25C14 11.8023 13.5523 12.25 13 12.25H3C2.44772 12.25 2 11.8023 2 11.25V4.25Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>' +
            '</svg>'
        );
    }

    /* <svg width="16" height="16" */
    function homeIconSvg() {
        return (
            '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
            '<path d="M2 6.67L8 2L14 6.67M3.33 6V14H6.67V9.33H9.33V14H12.67V6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
            '</svg>'
        );
    }

    /* <svg width="16" height="16" */
    function chevronUpIconSvg() {
        return (
            '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
            '<path d="M4 10l4-4 4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
            '</svg>'
        );
    }

    /* <svg width="16" height="16" */
    function fileIconSvg() {
        return (
            '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
            '<path d="M4.5 2.5H9L11.5 5V13C11.5 13.2761 11.2761 13.5 11 13.5H4.5C4.22386 13.5 4 13.2761 4 13V3C4 2.72386 4.22386 2.5 4.5 2.5Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>' +
            '<path d="M9 2.5V5H11.5" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>' +
            '</svg>'
        );
    }

    /* <svg width="16" height="16" */
    function lockIconSvg() {
        return (
            '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
            '<rect x="3.5" y="7.25" width="9" height="6.25" rx="1" stroke="currentColor" stroke-width="1.5"/>' +
            '<path d="M5.5 7.25V5A2.5 2.5 0 0 1 10.5 5V7.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
            '</svg>'
        );
    }

    /* <svg width="16" height="16" */
    function archiveIconSvg() {
        return glyph('archive');
    }

    function glyph(name) {
        var glyphs = globalThis.CloudeGlyphs;
        if (!glyphs || typeof glyphs.glyphSvg !== 'function') {
            console.error('SessionStatusUI: the glyph module is not loaded, icon:', name);
            return '';
        }
        return glyphs.glyphSvg(name);
    }

    window.SessionStatusUI = {
        escapeAttr,
        normalizeStatus,
        dotHtml,
        labelFor,
        labelWithSource,
        markUnreadHtml,
        trashIconSvg,
        closeIconSvg,
        restartIconSvg,
        pencilIconSvg,
        envelopeOutlineSvg,
        envelopeFilledSvg,
        folderIconSvg,
        fileIconSvg,
        lockIconSvg,
        archiveIconSvg,
        homeIconSvg,
        chevronUpIconSvg,
    };
    console.log('[SessionStatusUI Module] Exported as window.SessionStatusUI');
})();
