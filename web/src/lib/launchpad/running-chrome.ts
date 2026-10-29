import { hostDocument } from '../sessions/env';

const COUNT_ID = 'running-sessions-count';
/*  hidden  */
const SECTION_ID = 'running-sessions-section';

export interface RunningChrome {
    /* did not answer */
    setCount(text: string, listingOk: boolean): void;
    setSectionVisible(visible: boolean): void;
}

export function browserRunningChrome(): RunningChrome {
    return {
        setCount(text: string, listingOk: boolean): void {
            const doc = hostDocument();
            const el = doc && doc.getElementById(COUNT_ID);
            if (!el) return;
            el.textContent = text;
            el.setAttribute('data-listing-ok', listingOk ? '1' : '0');
        },
        setSectionVisible(visible: boolean): void {
            const doc = hostDocument();
            const el = doc && doc.getElementById(SECTION_ID);
            if (!el) return;
            (el as HTMLElement).style.display = visible ? '' : 'none';
        },
    };
}
