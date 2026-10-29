
const TOGGLE_ID = 'projects-show-archived-toggle';

let archiveClick: (() => void) | null = null;

export interface ProjectChromeControl {
    setArchivedToggle(on: boolean, title: string): void;
    bindArchivedToggle(onClick: () => void): void;
}

export function browserControl(): ProjectChromeControl {
    return {
        setArchivedToggle(on: boolean, title: string): void {
            const btn = document.getElementById(TOGGLE_ID);
            if (!btn) return;
            btn.setAttribute('aria-pressed', String(!!on));
            btn.classList.toggle('is-on', !!on);
            btn.setAttribute('title', title);
        },
        bindArchivedToggle(onClick: () => void): void {
            const btn = document.getElementById(TOGGLE_ID);
            if (!btn) return;
            archiveClick = onClick;
            if ((btn as HTMLElement).dataset.cloudeArchivedBound === '1') return;
            (btn as HTMLElement).dataset.cloudeArchivedBound = '1';
            btn.addEventListener('click', () => {
                if (archiveClick) archiveClick();
            });
        },
    };
}
