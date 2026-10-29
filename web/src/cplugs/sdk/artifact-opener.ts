
export interface PostedPage { item: number; title: string }

export type PostedPageOpener = (page: PostedPage) => Promise<boolean>;

let opener: PostedPageOpener | null = null;

export function registerPostedPageOpener(fn: PostedPageOpener): void {
  opener = fn;
}

export function postedPageOpener(): PostedPageOpener | null {
  return opener;
}

export function resetPostedPageOpener(): void {
  opener = null;
}
