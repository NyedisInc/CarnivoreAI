import { untrack } from 'svelte';
import { activeTerminalSlot } from '../../opscenter/lib/active-terminal';
import { retargetFiles } from '../../opscenter/cells/terminal-live/actions';
import { PRIMARY_SLOT } from '../../opscenter/engine/model';
import { panelPins } from '../widget-bars/panel-pins.svelte';
import { filesDrawer, listenFileDrawer } from './files.svelte';

let stop: (() => void) | null = null;

/* the page terminal */
export function followSlot(slot: string): boolean {
    if (!filesDrawer.open || panelPins.filesHeld) return false;
    return retargetFiles(slot) || (slot !== PRIMARY_SLOT && retargetFiles(PRIMARY_SLOT));
}

export function followActiveTerminal(): () => void {
    if (stop) return stop;
    listenFileDrawer();
    let last = '';
    const undo = $effect.root(() => {
        $effect(() => {
            const slot = activeTerminalSlot();
            if (slot === last) return;
            last = slot;
            untrack(() => followSlot(slot));
        });
    });
    stop = () => {
        undo();
        stop = null;
    };
    return stop;
}
