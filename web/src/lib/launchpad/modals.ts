import { openModal } from '../modal';
import ChoiceModal from './ChoiceModal.svelte';
import CloneModal from './CloneModal.svelte';
import EditProjectModal from './EditProjectModal.svelte';
import ProjectFolderModal from './ProjectFolderModal.svelte';
import ProjectNameModal from './ProjectNameModal.svelte';
import type {
    ChoiceOptions,
    ClonedProject,
    EditResult,
    FolderChoice,
    ProjectDetails,
} from './modal-types';

export interface NameRequest {
    title: string;
    confirmLabel: string;
    defaultName?: string;
    pathHint?: string | null;
}

export interface FolderRequest {
    name: string;
    defaultParent: () => Promise<string | null>;
    openPicker: (() => Promise<string | null>) | null;
    remote?: { label: string; creates?: boolean; browse?: Promise<string | null> } | null;
    confirmLabel?: string;
}

export interface EditRequest {
    projectName: string;
    projectPath: string;
    projectDescription?: string | null;
    projectDefaultLaunchProfile?: string | null;
    projectColor?: string | null;
    projectId?: number | null;
}

export interface CloneRequest {
    clone: (payload: {
        repoUrl: string;
        parentDir: string;
        description?: string;
    }) => Promise<ClonedProject>;
    defaultParentDir?: string;
    confirmLabel?: string;
}

export interface ModalOpeners {
    name(request: NameRequest): Promise<ProjectDetails | null>;
    folder(request: FolderRequest): Promise<FolderChoice | null>;
    choice(options: ChoiceOptions): Promise<string | null>;
    edit(request: EditRequest): Promise<EditResult | null>;
    clone(request: CloneRequest): Promise<ClonedProject | null>;
}

export function browserModals(): ModalOpeners {
    return {
        name: (request) => openModal<ProjectDetails, Record<string, unknown>>(
            ProjectNameModal as never,
            request as unknown as Record<string, unknown>,
        ),
        folder: (request) => openModal<FolderChoice, Record<string, unknown>>(
            ProjectFolderModal as never,
            request as unknown as Record<string, unknown>,
        ),
        choice: (options) => openModal<string, Record<string, unknown>>(
            ChoiceModal as never,
            options as unknown as Record<string, unknown>,
        ),
        edit: (request) => openModal<EditResult, Record<string, unknown>>(
            EditProjectModal as never,
            request as unknown as Record<string, unknown>,
        ),
        clone: (request) => openModal<ClonedProject, Record<string, unknown>>(
            CloneModal as never,
            request as unknown as Record<string, unknown>,
        ),
    };
}
