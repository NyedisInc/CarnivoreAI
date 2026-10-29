
type Opener = (href: string) => boolean;

let opener: Opener | null = null;

export function registerSettingsOpener(fn: Opener | null): void {
    opener = fn;
}

export function followSettingsLink(href: string): boolean {
    return opener ? opener(href) : false;
}
