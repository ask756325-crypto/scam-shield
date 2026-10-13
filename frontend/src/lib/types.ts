export type RiskLevel = "critical" | "high" | "medium" | "low" | "info";
export type FindingStatus = "open" | "escalated" | "confirmed" | "safe" | "resolved";
export type ChangeState = "new" | "changed" | "recurring" | "missing" | "resolved";

export interface User { id: number; email: string; name: string; created_at: string; last_login_at: string | null; email_verified: boolean }
export interface Session { user: User; organization: { id: number; name: string } | null; role: string | null }

export interface OfficialAccount { id?: number; platform: string; handle: string; profile_url?: string | null; external_id?: string | null }
export interface OfficialApp { id?: number; store: string; name?: string | null; app_id: string; track_id?: string | null; publisher_id?: string | null; publisher_name?: string | null; url?: string | null }

export interface Brand {
  id: number;
  name: string;
  aliases: string[];
  description: string;
  official_domains: string[];
  keywords: string[];
  website_url: string | null;
  additional_identifiers: string[];
  exclusion_rules: Record<string, boolean>;
  exclusion_rules_customised: string[];
  has_logo: boolean;
  logo_phash: string | null;
  logo_dhash: string | null;
  is_demo: boolean;
  schedule: ScheduleSummary | null;
  schedule_enabled: boolean;
  next_scheduled_at: string | null;
  official_accounts: OfficialAccount[];
  official_apps: OfficialApp[];
  created_at: string;
  updated_at: string;
  stats: {
    open_by_level?: Partial<Record<RiskLevel, number>>;
    open_review?: number;
    last_scan?: { id: number; status: string; finished_at: string | null; created_at: string } | null;
  };
}

export interface ScanSource {
  source: string; status: string; queries_total: number; queries_done: number; queries_failed: number;
  candidates: number; error: string | null; duration_ms: number | null; started_at: string | null; finished_at: string | null;
  query_outcomes?: Record<string, number>; failure_kind?: string | null; rate_limit?: Record<string, unknown> | null;
}

export interface Scan {
  id: number; brand_id: number; brand_name: string | null; trigger: string; mode: string; status: string;
  progress: number; stage: string; search_terms: string[]; candidates_collected: number; candidates_unique: number;
  excluded_official: number; findings_new: number; findings_changed: number; findings_recurring: number; findings_resolved: number;
  error: string | null; created_at: string; started_at: string | null; finished_at: string | null; sources: ScanSource[];
  schedule_id?: number | null; runner?: string | null; duration_ms?: number | null; sources_attempted?: string[]; source_failures?: string[];
  findings_updated?: number; findings_missing?: number; findings_unverified?: number;
}

export type ScheduleState = "active" | "paused" | "disabled";
export type Frequency = "interval" | "daily" | "weekly";
export interface ScheduleSummary { state: ScheduleState; description: string; next_run_at: string | null; last_outcome: string | null; consecutive_failures: number }
export interface Schedule {
  id: number; brand_id: number; brand_name?: string; state: ScheduleState; frequency: Frequency; interval_hours: number; time_of_day: string;
  weekdays: number[]; timezone: string; sources: string[] | null; description: string; next_run_at: string | null; next_run_local: string | null;
  upcoming: { utc: string; local: string }[]; last_run_at: string | null; last_scan_id: number | null; last_outcome: string | null;
  last_error: string | null; consecutive_failures: number; paused_reason: string | null; created_at: string; updated_at: string;
}
export interface SchedulerStatus { healthy: boolean; last_tick_at: string | null; runner: string | null; tick_seconds: number; in_this_process: boolean; max_concurrent_scans: number; message: string | null }
export type ChangeKind = "new" | "changed" | "recurring" | "reappeared" | "missing" | "resolved" | "unverified";
export interface ScanChange {
  change: ChangeKind; changed_fields: string[]; previous: Record<string, unknown>; current: Record<string, unknown>;
  risk_before: RiskLevel | null; risk_after: RiskLevel | null; missed_scans: number;
  finding: { id: number; status: FindingStatus; risk_level: RiskLevel; risk_score: number; change_state: ChangeState; classification: string };
  candidate: { name: string; handle: string | null; platform: string; kind: string; source: string; source_type: string; avatar_url: string | null; external_id: string };
}

export interface Candidate {
  id: number; source: string; source_type: "live" | "simulated" | "imported"; kind: "account" | "app" | "domain"; external_id: string;
  name: string; handle: string | null; url: string | null; description: string; avatar_url: string | null;
  publisher_name: string | null; publisher_id: string | null; external_links: string[]; metadata: Record<string, unknown>;
  provenance: Record<string, unknown>; first_observed_at: string; last_observed_at: string; source_created_at: string | null;
  platform: string;
}

export interface SignalData { name: string; evaluated: boolean; score: number; detail: string; evidence: string[]; data: Record<string, unknown> }

export interface Decision { id: number; action: string; note: string; created_at: string; user: string; from_status?: FindingStatus | null; to_status?: FindingStatus | null }

export interface Inference { group: string; group_label: string; signal: string; label: string; evaluated: boolean; score: number; statement: string; evidence: string[]; corroborates: boolean }
export interface IndicatorRef { kind: string; label: string; value: string; field: string }
export interface Evidence {
  observed_facts: { label: string; value: string; field: string }[];
  inferences: Inference[];
  comparison: {
    brand_name: string; matched_brand_name: string | null; aliases: string[]; logo: { available: boolean; phash: string | null; dhash: string | null };
    official_domains: string[]; description_reference: boolean; note: string;
    official_apps: { store: string; name: string | null; app_id: string; publisher_id: string | null; publisher_name: string | null; same_store: boolean }[];
    official_accounts: { platform: string; handle: string; profile_url: string | null }[];
  };
  provenance: { source: string; source_type: string; source_type_note: string; adapter: string | null; endpoint: string | null; queries: string[]; first_observed_at: string; last_observed_at: string; collected_at: string; content_hash: string };
  indicators: IndicatorRef[];
  disclaimer: string;
}
export interface RelatedGroup {
  kind: string; label: string; value: string; observed_in: string; count: number;
  candidates: { finding_id: number; name: string; handle: string | null; platform: string; kind: string; brand_name: string; risk_level: RiskLevel; status: FindingStatus; source_type: string; observed_in: string }[];
}

export interface Finding {
  id: number; brand_id: number; brand_name: string | null; risk_score: number; risk_level: RiskLevel; classification: string;
  detection_type?: string | null;
  assignee?: { id: number; name: string; email: string } | null;
  signal_scores?: Record<string, { score: number; evaluated: boolean; detail: string }>;
  not_evaluated?: string[];
  explanation: string; status: FindingStatus; change_state: ChangeState; corroborating_groups: string[];
  first_seen_scan_id: number | null; last_seen_scan_id: number | null; created_at: string; updated_at: string; candidate: Candidate;
  signals?: { signals: Record<string, SignalData>; groups: Record<string, number | null>; not_evaluated: string[] };
  reasons?: string[];
  decisions?: Decision[];
  observations?: { scan_id: number; observed_at: string; risk_score: number | null; content_hash: string; trigger: string }[];
  evidence?: Evidence;
}

export type SourceState = "live" | "simulated" | "disabled" | "unavailable";
export type SourceHealthValue = "not_tested" | "operational" | "no_results" | "degraded" | "rate_limited" | "failing" | "invalid_config" | "simulated";
export interface SourceCheck { id: number; outcome: string; detail: string; result_count: number | null; latency_ms: number | null; rate_limit: Record<string, { limit?: number | null; remaining?: number | null; reset_in?: number | null }> | null; at: string }
/** One integration in the source registry. Every value comes from a real scan or connectivity test. */
export interface SourceHealth {
  name: string; label: string; platform: string; category: string; integration_type: string; integration: string; reliability: string;
  source_type: string; docs_url: string | null; notes: string; enabled: boolean;
  state: SourceState; health: SourceHealthValue; health_detail: string; observed_at: string | null; observed_via: "scan" | "test" | null;
  config: { valid: boolean; problems: string[] };
  auth: { status: "not_required" | "configured"; label: string; credentials: { instance: string; configured: boolean; source: string | null }[]; unused_tokens_for?: string[] };
  last_success: { at: string; via: "scan" | "test"; scan_id: number | null; detail: string | null } | null;
  last_error: { at: string; via: "scan" | "test"; scan_id: number | null; kind: string; message: string | null } | null;
  last_attempted_scan: { scan_id: number; status: string; at: string | null; candidates: number; query_outcomes: Record<string, number> } | null;
  last_test: SourceCheck | null;
  rate_limit: { documented: string | null; observed: { values: Record<string, { limit?: number | null; remaining?: number | null; reset_in?: number | null }>; at: string; via: string } | null; last_rate_limited_at: string | null };
  // flat fields (dashboard / sidebar)
  status: string; unavailable?: boolean; last_success_at?: string | null; last_success_scan_id?: number | null; checked_at: string | null; detail: string; failure_kind?: string | null;
}

export type Level4 = "critical" | "high" | "medium" | "low";

export interface Dashboard {
  empty: boolean;
  brands: number;
  period: { days: number | null; since: string | null };
  metrics: {
    candidates_scanned: number; scans_in_period: number; scans_total: number; candidates_last_scan: number;
    review_required: number; high_risk_open: number; critical_open: number; official_excluded: number;
    sources_enabled: number; sources_unavailable: number; sources_degraded: number; confirmed: number; marked_safe: number;
  };
  severity: Record<Level4, number>;
  severity_period: Record<Level4, number>;
  severity_by_platform: ({ platform: string; total: number } & Record<Level4, number>)[];
  review: { open_by_level: Record<"critical" | "high" | "medium", number>; oldest_open_at: string | null; new_or_changed: number; top: Finding[] };
  source_health: SourceHealth[];
  unavailable_sources: string[];
  recent_scans: Scan[];
  scan_series: { scan_id: number; at: string; candidates: number; new: number; changed: number; resolved: number; excluded: number; mode: string; status: string }[];
  last_scan: Scan | null;
  last_completed_scan: Scan | null;
}

export interface Paged<T> { total: number; items: T[] }

export interface ExclusionRule {
  id: string; kind: "account" | "app"; default: boolean; label: string; description: string; enabled: boolean;
  stats?: { count: number; last_at: string | null };
}

export interface Registry {
  brand_id: number;
  can_edit_rules: boolean;
  rules: ExclusionRule[];
  exact_identifiers: { type: string; platform: string | null; value: string; rules: string[]; note?: string | null }[];
  similarity_reference: {
    names: string[]; keywords: string[]; additional_identifiers: string[]; has_description: boolean;
    logo: { phash: string; dhash: string } | null; note: string;
  };
}
