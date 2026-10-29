
export interface PostedPage { item: number; title: string }

export type PostedPageOpener = (page: PostedPage) => Promise<boolean>;

let opener: PostedPageOpener | null = null;
let isOn: () => boolean = () => true;

export function registerPostedPageOpener(fn: PostedPageOpener, enabled: () => boolean = () => true): void {
  opener = fn;
  isOn = enabled;
}

export function postedPageOpener(): PostedPageOpener | null {
  return opener !== null && isOn() ? opener : null;
}

export function resetPostedPageOpener(): void {
  opener = null;
  isOn = () => true;
}
