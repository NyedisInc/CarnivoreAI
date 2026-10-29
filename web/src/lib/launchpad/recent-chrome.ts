
const COUNT_ID = 'recent-sessions-count';
const TOGGLE_ID = 'recent-show-deleted-toggle';
/*  hidden  */
const SECTION_ID = 'recent-sessions-section';

let archiveClick: (() => void) | null = null;

export interface RecentChrome {
    setCount(text: string, state: string): void;
    setSectionVisible(visible: boolean): void;
    setArchiveToggle(on: boolean, title: string): void;
    bindArchiveToggle(onClick: () => void): void;
}

export function browserChrome(): RecentChrome {
    return {
        setCount(text: string, state: string): void {
            const el = document.getElementById(COUNT_ID);
            if (!el) return;
            el.textContent = text;
            el.setAttribute('data-state', state);
        },

        setSectionVisible(visible: boolean): void {
            const el = document.getElementById(SECTION_ID);
            if (!el) return;
            el.style.display = visible ? '' : 'none';
        },

        setArchiveToggle(on: boolean, title: string): void {
            const el = document.getElementById(TOGGLE_ID);
            if (!el) return;
            el.setAttribute('aria-pressed', String(!!on));
            el.classList.toggle('is-on', !!on);
            el.setAttribute('title', title);
        },

        bindArchiveToggle(onClick: () => void): void {
            const el = document.getElementById(TOGGLE_ID);
            if (!el) return;
            archiveClick = onClick;
            if (el.dataset.recentArchiveBound === '1') return;
            el.dataset.recentArchiveBound = '1';
            el.addEventListener('click', () => {
                if (archiveClick) archiveClick();
            });
        },
    };
}
