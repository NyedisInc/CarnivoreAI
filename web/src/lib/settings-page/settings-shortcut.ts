import { openSettingsScreen } from './screen-host';

export const SETTINGS_KEY_ROWS: ReadonlyArray<{ keys: string; labelKey: string }> = [
    { keys: 'cmd ,', labelKey: 'keys.page.settings.open' },
];

type ChordEvent = Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey' | 'altKey' | 'shiftKey' | 'preventDefault'>;

export const isSettingsChord = (event: ChordEvent, mac: boolean): boolean =>
    event.key === ',' && (mac ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey) && !event.altKey && !event.shiftKey;

export const handleSettingsKey = (event: ChordEvent, mac: boolean, open: () => unknown = openSettingsScreen): boolean => {
    if (!isSettingsChord(event, mac)) return false;
    event.preventDefault();
    open();
    return true;
};

export const installSettingsShortcut = (win: Window = window): (() => void) => {
    if ('carnivoreDesktop' in win) return () => undefined;
    const mac = /mac/i.test(win.navigator.platform);
    const onKey = (event: KeyboardEvent): void => {
        handleSettingsKey(event, mac);
    };
    win.addEventListener('keydown', onKey, true);
    return () => win.removeEventListener('keydown', onKey, true);
};
