import { apiFetch } from "@/lib/api";

export type LabAccess = {
  operator_authorized: true;
  server_enabled: boolean;
  namespace: { id: string; demo_user_id: string; enabled: boolean; revision: number; rail: string } | null;
  execution_available: false;
  reason: string;
  limits: { mutations_per_minute: number; active_scenarios: number; candidate_attempts: number;
    scenario_seconds: number; payload_bytes: number };
};

export function labAccess() {
  return apiFetch<LabAccess>("/attack-lab/access");
}

export function createLabWorkspace() {
  return apiFetch<LabAccess>("/attack-lab/namespaces", { method: "POST", body: "{}" });
}

export function labControl(id: string, enabled: boolean, revision: number) {
  return apiFetch<LabAccess>(`/attack-lab/namespaces/${encodeURIComponent(id)}/control`, {
    method: "POST", body: JSON.stringify({ enabled, expected_revision: revision }),
  });
}
