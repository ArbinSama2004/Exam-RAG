/**
 * Typed access to the ExamRAG backend API.
 *
 * MCQ and FAQ calls are added in the phases that implement them; this module
 * owns the base URL, the response types and the error convention.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type DocumentPurpose = "STUDY_MATERIAL" | "PAST_PAPER";

export type ProcessingStatus = "UPLOADED" | "PROCESSING" | "READY" | "FAILED";

export type IngestionStage =
  | "QUEUED"
  | "LOADING"
  | "CONVERTING"
  | "CLEANING"
  | "CHUNKING"
  | "EMBEDDING"
  | "INDEXING"
  | "COMPLETED";

export type DocumentType = "PDF" | "DOCX" | "MARKDOWN" | "TXT";

export interface HealthResponse {
  status: "ok";
  app: string;
  version: string;
  environment: string;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  document_type: DocumentType;
  purpose: DocumentPurpose;
  status: ProcessingStatus;
  size_bytes: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface IngestionStatus {
  document_id: string;
  job_id: string;
  status: ProcessingStatus;
  stage: IngestionStage;
  chunk_count: number;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface UploadResponse {
  document: DocumentSummary;
  job_id: string;
  reused: boolean;
}

/** File extensions the backend accepts, for the file picker. */
export const ACCEPTED_EXTENSIONS = ".pdf,.docx,.md,.markdown,.txt";

/** A document is still being worked on until it reaches one of these. */
export function isTerminal(status: ProcessingStatus): boolean {
  return status === "READY" || status === "FAILED";
}

/** An error carrying the backend's own message, so the UI can show it. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

/**
 * Pull the message out of a FastAPI error body.
 *
 * `detail` is a string for our own HTTPExceptions and an array of issues for
 * validation failures, so both shapes are handled.
 */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body.detail)) {
      const first = body.detail[0] as { msg?: string } | undefined;
      if (first?.msg) {
        return first.msg;
      }
    }
  } catch {
    // Not a JSON body; fall through to the status text.
  }
  return `Request failed with status ${response.status}`;
}

export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function fetchDocuments(purpose?: DocumentPurpose): Promise<DocumentSummary[]> {
  const query = purpose ? `?purpose=${purpose}` : "";
  return request<DocumentSummary[]>(`/documents${query}`);
}

export function fetchIngestionStatus(documentId: string): Promise<IngestionStatus> {
  return request<IngestionStatus>(`/documents/${documentId}/status`);
}

export function uploadDocument(file: File, purpose: DocumentPurpose): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("purpose", purpose);
  return request<UploadResponse>("/documents", { method: "POST", body: form });
}
