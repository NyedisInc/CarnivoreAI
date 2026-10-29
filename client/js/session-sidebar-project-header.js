/*  hidden  */

console.log('[SessionSidebarProjectHeader Module] Loading...');

(function () {
    function ledHtml(rows, collapsed, showLight) {
        if (!collapsed || showLight === false) return '';
        const led = (rows && rows.some((r) => r.kind !== 'browser') && window.SessionStatusSummary)
            ? window.SessionStatusSummary.summaryHtml(rows)
            : '';
        return led ? `<span class="session-sidebar-group__project-led">${led}</span>` : '';
    }

    function iconHtml(name) {
        if (!name) return '';
        const glyphs = globalThis.CloudeGlyphs;
        const svg = (glyphs && typeof glyphs.glyphSvg === 'function')
            ? glyphs.glyphSvg(name, 12)
            : '';
        return svg ? `<span class="session-sidebar-group__icon" aria-hidden="true">${svg}</span>` : '';
    }

    function iconForBand(key, isProject) {
        if (isProject) return 'folder';
        if (key === 'pinned') return 'pin';
        if (key === 'open') return 'bolt';
        if (key === 'sleeping') return 'sleeping-agent';
        if (key === 'terminals') return 'terminal';
        if (key === 'browsers') return 'globe';
        if (key === 'files') return 'code';
        const kinds = window.SessionSidebarKindGroups;
        const sectionIcon = kinds && typeof kinds.pageSectionIcon === 'function' ? kinds.pageSectionIcon(key) : null;
        if (sectionIcon) return sectionIcon;
        if (key === 'layouts') return 'grid';
        return null;
    }

    function pickedIconHtml(o) {
        const icons = window.SessionSidebarGroupIcon;
        const G = window.SessionSidebarGroupStore;
        if (o.bandKind !== 'group' || !icons || !G) return '';
        return icons.headingMark(G.groupUuidOf(o.key));
    }

    function headingElementsFor(anchor) {
        const row = anchor && anchor.closest && anchor.closest('.session-sidebar-group__headerrow');
        const headerBtn = row ? row.querySelector('.session-sidebar-group__header') : null;
        const labelEl = headerBtn ? headerBtn.querySelector('.session-sidebar-group__label') : null;
        return { headerBtn, labelEl };
    }

    window.SessionSidebarProjectHeader = {
        ledHtml, iconHtml, iconForBand, pickedIconHtml, headingElementsFor,
    };
    console.log(
        '[SessionSidebarProjectHeader Module] Exported as window.SessionSidebarProjectHeader',
    );
})();
