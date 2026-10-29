import { contextFromTrigger, setMuteOverride, triggerHtml } from './row-context';
import { closeRowMenu, openRowMenu, rowMenuIsOpen, shiftHeld } from './row-open';
import { runCplug, runPluginItem } from './row-plugins';

export const rowMenuBridge = {
    triggerHtml,
    contextFromTrigger,
    setMuteOverride,
    shiftHeld,
    openRow: openRowMenu,
    isOpen: rowMenuIsOpen,
    closeRow: closeRowMenu,
    runPlugin: runPluginItem,
    runCplug,
};
