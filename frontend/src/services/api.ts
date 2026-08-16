/**
 * Typed access to the ExamRAG backend API.
 *
 * Feature-specific calls (upload, MCQ, FAQ) are added in the phases that
 * implement them; this module owns the base URL and the fetch conventions.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface HealthResponse {
  status: "ok";
  app: string;
  version: string;
  environment: string;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`Request to ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health");
}
