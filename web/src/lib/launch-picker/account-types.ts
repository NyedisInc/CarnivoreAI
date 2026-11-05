
export interface AccountChoice {
    id: string;
    name: string;
    color?: string | null;
    is_current?: boolean;
    provider?: string;
}

export interface RestartAccounts {
    options: AccountChoice[];
    selected_id?: string | null;
    current_id?: string | null;
    active_id?: string | null;
    pinned?: boolean;
    selected_by_provider?: Record<string, string | null>;
}
