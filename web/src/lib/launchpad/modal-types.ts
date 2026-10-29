
export interface ProjectDetails {
    name: string;
    description: string;
}

export interface ChoiceItem {
    key: string;
    label: string;
    sub?: string | null;
    disabled?: boolean;
    reason?: string | null;
}

export interface ChoiceOptions {
    title: string;
    hint?: string;
    items: ChoiceItem[];
    emptyMessage?: string | null;
    emptyKind?: string;
}

export interface FolderChoice {
    parent: string;
    path: string;
}

export interface EditResult {
    name: string;
    description: string;
    defaultLaunchProfile?: string;
    color?: string;
    nudge?: boolean;
    inbox?: boolean;
}

export interface ClonedProject {
    name: string;
    path: string;
    description?: string | null;
}

export interface RemoteFolderListing {
    status: 'ok';
    path: string;
    parent: string | null;
    entries: { name: string; path: string }[];
    truncated: boolean;
}

export type RemoteFolderAnswer =
    | RemoteFolderListing
    | { status: 'refused'; code: string }
    | { status: 'unavailable'; reason: string };

export interface FolderPickerSource {
    list(path: string | null): Promise<RemoteFolderListing>;
    title: string;
    truncatedText: string;
}
