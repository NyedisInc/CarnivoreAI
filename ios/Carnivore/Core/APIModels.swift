import Foundation


struct AuthTokensDTO: Codable, Sendable {
    let access_token: String
    let refresh_token: String?
    let expires_in: Int?
    let token_type: String?
}

struct PairVerifyResponseDTO: Codable, Sendable {
    let ok: Bool?
    let status: String?
    let access_token: String?
    let refresh_token: String?
    let expires_in: Int?
    let status_token: String?
    let device_name: String?
}

struct NativeDeviceRegisterBody: Encodable, Sendable {
    let platform: String
    let token: String
    let environment: String
    let bundle_id: String
    let app_version: String
    let payload_key: String
}

struct NativeDevicePublicDTO: Decodable, Sendable {
    let id: String
}


struct SessionListingSnapshotDTO: Decodable, Sendable {
    let sessions: [SessionRowDTO]
    let asleep: [AsleepSessionDTO]?
}

struct SessionRowDTO: Codable, Identifiable, Equatable, Sendable {
    let session: SessionInnerDTO
    let claude_title: String?
    let local_servers: [LocalServerDTO]?
    let session_backend: String?
    let tmux_session: String?
    let session_row_id: Int?
    let claude_session_uuid: String?
    let project_id: Int?
    let project_name: String?
    let label: String?
    let agent_type: String?
    let agent_family: String?
    let agent_wrapper_label: String?
    let running_model: String?
    let running_context_used_pct: Double?
    let pinned_theme: String?
    let activity_status: String?
    let unread: Bool?
    let startup_gate: String?
    let notifications_muted: Bool?
    let host_key: String?
    let host_label: String?
    let background_processes: BackgroundProcessesDTO?
    let subagent_count: Int?
    let active_timer_count: Int?

    var id: String { session.id }

    var displayName: String {
        if let label, !label.isEmpty { return label }
        if let title = claude_title, !title.isEmpty { return title }
        if let tmux = tmux_session, !tmux.isEmpty { return tmux }
        return session.id
    }

    var effectiveStatus: String {
        if startup_gate == "awaiting_startup_prompt" { return "question" }
        return activity_status ?? "unknown"
    }

    var projectGroup: String {
        if let name = project_name, !name.isEmpty { return name }
        let last = URL(fileURLWithPath: session.working_dir).lastPathComponent
        return last.isEmpty ? "Unassigned" : last
    }

    var backgroundShellCount: Int { background_processes?.count ?? 0 }
    var leftoverShellCount: Int { background_processes?.leftover ?? 0 }
    var listeningPortCount: Int { local_servers?.count ?? 0 }

    var hasWorkBadge: Bool {
        backgroundShellCount > 0 || (subagent_count ?? 0) > 0 || listeningPortCount > 0 || (active_timer_count ?? 0) > 0
    }
}

struct SessionInnerDTO: Codable, Equatable, Sendable {
    let id: String
    let pty_pid: Int?
    let working_dir: String
    let status: String?
    let created_at: String?
    let last_activity: String?
    let agent_type: String?
    let tmux_session: String?
    let model: String?
}

struct LocalServerDTO: Codable, Equatable, Identifiable, Sendable {
    let port: Int
    let url: String
    let address: String?
    let process: String?
    var id: Int { port }
}

struct BackgroundProcessesDTO: Codable, Equatable, Sendable {
    let state: String?
    let count: Int?
    let leftover: Int?
}

struct AsleepSessionDTO: Codable, Identifiable, Equatable, Sendable {
    let session_uuid: String?
    let title: String?
    let label: String?
    let tmux_session: String?
    let project_name: String?
    let working_dir: String?
    let agent_family: String?
    let host_label: String?

    var id: String { session_uuid ?? tmux_session ?? UUID().uuidString }
    var displayName: String { label ?? title ?? tmux_session ?? session_uuid ?? "Asleep session" }
}


struct ApprovalsResponseDTO: Decodable, Sendable {
    let items: [ApprovalItemDTO]
    let version: Int?
}

struct ApprovalItemDTO: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let source: String
    let host: String?
    let host_label: String?
    let session_id: String
    let session_name: String?
    let tmux_session: String?
    let project: String?
    let family: String?
    let kind: String
    let question: String?
    let body: String?
    let options: [String]?
    let multi_select: Bool?
    let has_other: Bool?
    let fingerprint: String?
    let plain_yes: String?
    let plain_no: String?
    let beast_would_answer: Bool?
    let startup_kind: String?
    let caller: String?
    let action: String?
    let summary: String?
    let created_at: String?
    let confirm_text: String?

    var displayTitle: String {
        if let q = question, !q.isEmpty { return q }
        if let s = summary, !s.isEmpty { return s }
        if let a = action, !a.isEmpty { return a }
        return kind
    }

    var displayAgent: String {
        session_name ?? caller ?? tmux_session ?? session_id
    }
}


struct BeastModeStateDTO: Codable, Equatable, Sendable {
    let enabled: Bool
    let prompts: Bool
    let since: String?
    let until: String?
    let pending_count: Int?
}


struct PackActivityDTO: Codable, Equatable, Sendable {
    let computers: [PackComputerDTO]?
    let items: [PackLiveEntryDTO]?
    let live: [PackLiveEntryDTO]?
    let history: [PackHistoryEntryDTO]?

    var liveItems: [PackLiveEntryDTO] {
        if let items { return items.filter { $0.live ?? true } }
        return live ?? []
    }

    var selfComputerLabel: String? {
        guard let selfComp = computers?.first(where: { $0.is_self == true || $0.is_local == true }) else { return nil }
        let trimmed = selfComp.label.trimmingCharacters(in: .whitespacesAndNewlines)
        let lower = trimmed.lowercased()
        guard !trimmed.isEmpty, lower != "this computer", lower != "this machine", lower != "local" else { return nil }
        return trimmed
    }
}

struct PackComputerDTO: Codable, Identifiable, Equatable, Sendable {
    let install_id: String?
    let host_key: String?
    let label: String
    let is_self: Bool?
    let is_local: Bool?
    let online: Bool?
    let status: String?
    let state: String?
    let cpu_pct: Double?
    let memory_pct: Double?
    let ram_pct: Double?
    let live_agents: Int?
    let live_commands: Int?
    let live_delegated_agents: Int?
    let live_total: Int?
    let running_agents: Int?
    let running_jobs: Int?
    let active_count: Int?
    let waiting_count: Int?

    var id: String { install_id ?? host_key ?? label }
    var effectiveOnline: Bool {
        if let online { return online }
        let s = (status ?? state ?? "up").lowercased()
        return s == "up" || s == "online" || s == "ok" || s == "local"
    }
    var effectiveMemoryPct: Double? { ram_pct ?? memory_pct }
    var effectiveAgentsCount: Int { live_agents ?? running_agents ?? active_count ?? 0 }
    var effectiveJobsCount: Int { (live_commands ?? 0) + (live_delegated_agents ?? 0) + (running_jobs ?? 0) }
}

struct PackLiveEntryDTO: Codable, Identifiable, Equatable, Sendable {
    let id: String?
    let item_type: String?
    let kind: String?
    let live: Bool?
    let title: String?
    let name: String?
    let label: String?
    let computer_id: String?
    let computer_label: String?
    let host_key: String?
    let host_label: String?
    let project: String?
    let status: String?
    let activity_status: String?
    let session_uuid: String?
    let session_id: String?
    let command: String?

    var stableId: String { id ?? session_id ?? session_uuid ?? "\(effectiveComputerId)-\(displayName)" }
    var displayName: String { title ?? label ?? name ?? command ?? "Job" }
    var effectiveStatus: String { status ?? activity_status ?? "working" }
    var effectiveComputerId: String { computer_id ?? host_key ?? "" }
    var effectiveComputerLabel: String? { computer_label ?? host_label }
    var effectiveSessionId: String? { session_id ?? session_uuid }
}

struct PackHistoryEntryDTO: Codable, Identifiable, Equatable, Sendable {
    let id: String?
    let kind: String?
    let name: String?
    let command: String?
    let host_key: String?
    let host_label: String?
    let status: String?
    let finished_at: String?
    let duration_s: Double?

    var stableId: String { id ?? "\(host_key ?? "")-\(finished_at ?? "")-\(name ?? command ?? "")" }
}

struct SwarmRosterDTO: Codable, Equatable, Sendable {
    let agents: [SwarmAgentDTO]?
}

struct SwarmAgentDTO: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let display_name: String?
    let name: String?
    let role: String?
    let scope: String?
    let status: String?
    let state: String?
    let session_id: String?
    let project_name: String?
    let waiting_question: String?

    var effectiveName: String { display_name ?? name ?? id }
    var effectiveState: String { status ?? state ?? "asleep" }
}


struct BackgroundWorkDTO: Decodable, Equatable, Sendable {
    let state: String
    let family: String?
    let leftovers: Int?
    let detail: String?
    let processes: [BackgroundProcessDTO]?
}

struct BackgroundProcessDTO: Decodable, Identifiable, Equatable, Sendable {
    let pid: Int
    let start: String?
    let command: String?
    let label: String?
    let started_at: String?
    let children: Int?
    let leftover: Bool?
    let owner_label: String?

    var id: Int { pid }
}

struct SessionGitStatusDTO: Decodable, Equatable, Sendable {
    let state: String
    let branch: String?
    let ahead: Int?
    let behind: Int?
    let files: [GitFileDTO]?
}

struct GitFileDTO: Decodable, Identifiable, Equatable, Sendable {
    let path: String
    let status: String?
    let staged: Bool?
    let added: Int?
    let removed: Int?
    var id: String { path }
}

struct SessionGitDiffDTO: Decodable, Equatable, Sendable {
    let state: String
    let path: String?
    let text: String?
    let truncated: Bool?
}

struct ProjectDTO: Codable, Identifiable, Equatable, Sendable {
    let id: Int?
    let name: String?
    let display_name: String?
    let path: String?
    let working_dir: String?

    var stableId: String { "\(id ?? 0)-\(effectiveName)" }
    var effectiveName: String { display_name ?? name ?? "Project" }
    var effectivePath: String { path ?? working_dir ?? "~" }
}

struct ProjectsListResponseDTO: Decodable, Sendable {
    let projects: [ProjectDTO]?
}

struct UploadResponseDTO: Decodable, Sendable {
    let path: String
    let filename: String?
}
