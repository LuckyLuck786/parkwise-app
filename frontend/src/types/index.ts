/* Shared API types (mirrors the FastAPI payloads). */

export type Role = "driver" | "admin" | "gate_operator";
export type VehicleType = "two_wheeler" | "four_wheeler";
export type BayState = "free" | "allotted" | "occupied" | "blocked" | "unknown";

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  priority_tier: number;
  needs_accessible: boolean;
  destination_building_id?: string | null;
}

export interface Vehicle {
  id: string;
  plate_or_tag_id: string;
  type: VehicleType;
  active_today: boolean;
  created_at?: string;
  masked?: boolean;
}

export interface Building {
  id: string;
  name: string;
  lat?: number | null;
  lng?: number | null;
}

export interface LotCounts {
  free: number;
  allotted: number;
  occupied: number;
  blocked: number;
  unknown: number;
  total: number;
}

export interface Prediction {
  lot_id: string;
  lot_name: string;
  capacity: number;
  current_occupancy: number;
  occupancy_pct: number;
  is_full_now: boolean;
  predicted_fill_time: string;
  minutes_until_full: number | null;
  warning_message: string;
  confidence: "high" | "medium" | "low";
  confidence_note: string;
  method: string;
  heuristic_label: string;
  within_warning_window?: boolean;
}

export interface LotSummary {
  id: string;
  name: string;
  lat?: number | null;
  lng?: number | null;
  capacity: number;
  counts: LotCounts;
  used: number;
  free: number;
  occupancy_pct: number;
  low_confidence_bays: number;
  is_full: boolean;
  prediction?: Prediction;
  warning?: { active: boolean; message?: string; threshold_minutes?: number };
}

export interface BayAllotment {
  status: string;
  tier?: number | null;
  plate?: string | null;
}

export interface Bay {
  id: string;
  label: string;
  type: VehicleType;
  is_accessible: boolean;
  reserved_tier?: number | null;
  x: number;
  y: number;
  state: BayState;
  nearest_building_id?: string | null;
  nearest_building?: string | null;
  confidence: number;
  state_source: string;
  low_confidence: boolean;
  last_sensor_ts?: string | null;
  allotment?: BayAllotment | null;
}

export interface LotBaysResponse {
  lot: { id: string; name: string; capacity: number; lat?: number | null; lng?: number | null };
  bays: Bay[];
}

export interface Explanation {
  rule_applied: string;
  user_tier?: number;
  vehicle_type?: string;
  preferred_lot?: string;
  destination?: string;
  candidates_considered?: number;
  rejections?: Record<string, number>;
  chosen?: { bay: string; lot: string; reason: string; walk_meters_estimate?: number };
  alternatives?: { lot: string; free_bays: number; estimated_drive_time_mins: number }[];
  rules_in_effect?: Record<string, unknown>;
  waitlist_position?: number;
  [k: string]: unknown;
}

export interface AllocationResult {
  success: boolean;
  status: "allotted" | "offered_alternative" | "waitlisted" | "rejected";
  bay?: {
    id: string;
    label: string;
    lot_name: string;
    type: string;
    is_accessible: boolean;
    reserved_tier?: number | null;
    x: number;
    y: number;
  };
  lot?: { id: string; name: string };
  alternative_lot?: {
    id: string;
    name: string;
    estimated_drive_time_mins: number;
    available_bays: number;
  } | null;
  waitlist_position?: number;
  message: string;
  explanation: Explanation;
  allotment_id?: string;
}

export interface GateScanResponse {
  success: boolean;
  message: string;
  allocation: AllocationResult | null;
}

export interface CurrentParking {
  allotment_id: string;
  status: string;
  bay: {
    id: string;
    label: string;
    lot_id: string;
    lot_name: string;
    is_accessible: boolean;
    type: string;
    x: number;
    y: number;
  };
  allotted_at?: string;
  arrived_at?: string;
  destination?: string | null;
  walk_hint: { meters_estimate: number; minutes_estimate: number; text: string; note: string };
  explanation?: Explanation;
}

export interface MeStatus {
  user: User;
  active_vehicle: { id: string; plate_or_tag_id: string; type: VehicleType } | null;
  vehicle_count: number;
  current_parking: CurrentParking | null;
  waitlist: {
    id: string;
    position: number;
    joined_at?: string;
    preferred_lot?: string | null;
  } | null;
  unread_notifications: number;
  grace_minutes: number;
  destination_building_id?: string | null;
}

export interface AppNotification {
  id: string;
  message: string;
  channel: string;
  ts?: string;
  read: boolean;
}

export interface RuleEntry {
  value: unknown;
  description: string;
  default: unknown;
}

export interface Conflict {
  audit_id: string;
  conflict_type: string;
  bay_id?: string;
  bay_label?: string;
  severity?: string;
  message?: string;
  confidence?: number;
  recommended_action?: string;
  ts?: string;
  suspected_vehicles?: string[];
}

export interface DeviceInfo {
  id: string;
  name: string;
  kind?: string;
  status: string;
  last_heartbeat?: string | null;
  heartbeat_age_seconds?: number | null;
  timeout_seconds: number;
  reachable: boolean;
}

export interface AuditEntry {
  id: string;
  actor: string;
  action: string;
  details?: Record<string, unknown> | null;
  ts?: string;
}

export interface NoShowStats {
  no_show_released: number;
  completed: number;
  cancelled: number;
  open: number;
  no_show_rate_pct: number;
  definition: string;
}

export interface Analytics {
  generated_at: string;
  lots: LotSummary[];
  queue_length: number;
  conflicts: Conflict[];
  conflict_count: number;
  no_show: NoShowStats;
  utilization_series: { date: string; occupied_bay_minutes: number; utilization_pct: number }[];
  devices: DeviceInfo[];
  tier_summary_today: Record<string, number>;
  audit: AuditEntry[];
  totals: { users: number; vehicles: number; bays: number; allotments_all_time: number };
}

export interface PolicyMetrics {
  policy: string;
  arrivals: number;
  parked: number;
  failed_entries: number;
  wasted_entries: number;
  avg_search_minutes: number | null;
  p90_search_minutes: number | null;
  avg_search_note?: string;
  utilization_pct: number;
  tier1_access_success_pct: number;
  tier1_arrivals: number;
  waitlisted: number;
  waitlist_resolved: number;
  occupied_bay_minutes: number;
}

export interface MetricsRun {
  run_id?: string;
  name: string;
  params: { seed: number; hours: number; scale: number; start: string };
  arrivals: number;
  assumptions: {
    model: string;
    baseline: string;
    parkwise: string;
    arrival_profile?: string;
    parameters: Record<string, unknown>;
  };
  baseline: PolicyMetrics;
  parkwise: PolicyMetrics;
  delta_parkwise_minus_baseline: Record<string, number | null>;
  generated_at: string;
  label: string;
}

export interface DemoState {
  clock: { virtual_now: string; real_now: string };
  counts: { free_bays: number; active_allotments: number; waitlist: number; notifications: number };
  version: number;
  input_source?: "live" | "simulated_only";
}
