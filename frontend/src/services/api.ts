/**
 * Typed access to the ExamRAG backend API.
 *
 * This module owns the base URL, the response types and the error convention.
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

export type Difficulty = "EASY" | "MEDIUM" | "HARD";

export interface QuizQuestionPublic {
  id: string;
  position: number;
  question: string;
  options: string[];
}

export interface QuizPublic {
  id: string;
  difficulty: Difficulty;
  topic: string | null;
  question_count: number;
  questions: QuizQuestionPublic[];
  created_at: string;
}

export interface AnswerResult {
  question_id: string;
  selected_index: number;
  correct_index: number;
  is_correct: boolean;
  explanation: string;
  source: string;
}

export interface QuizQuestionReview {
  id: string;
  position: number;
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
  source: string;
  selected_index: number | null;
  is_correct: boolean | null;
}

export interface QuizResult {
  quiz_id: string;
  score: number;
  total: number;
  correct: number;
  incorrect: number;
  unanswered: number;
  questions: QuizQuestionReview[];
  submitted_at: string;
}

export interface RetrievedChunk {
  chunk_id: string;
  document_id: string;
  filename: string;
  content: string;
  score: number;
  rank: number;
  page_number: number | null;
  heading: string | null;
  source: string;
}

export interface RetrievalComparison {
  query: string;
  vector: RetrievedChunk[];
  keyword: RetrievedChunk[];
  hybrid: RetrievedChunk[];
  hybrid_reranked: RetrievedChunk[];
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

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function generateQuiz(input: {
  documentIds: string[];
  count: number;
  difficulty: Difficulty;
  topic: string | null;
}): Promise<QuizPublic> {
  return postJson<QuizPublic>("/quizzes/generate", {
    document_ids: input.documentIds,
    count: input.count,
    difficulty: input.difficulty,
    topic: input.topic,
  });
}

export function answerQuestion(
  quizId: string,
  questionId: string,
  selectedIndex: number,
): Promise<AnswerResult> {
  return postJson<AnswerResult>(`/quizzes/${quizId}/answer`, {
    question_id: questionId,
    selected_index: selectedIndex,
  });
}

export function submitQuiz(quizId: string): Promise<QuizResult> {
  return postJson<QuizResult>(`/quizzes/${quizId}/submit`, {});
}

export function compareRetrieval(query: string, documentIds: string[]): Promise<RetrievalComparison> {
  return postJson<RetrievalComparison>("/retrieval/compare", {
    query,
    document_ids: documentIds,
  });
}

export interface FaqSource {
  document_id: string;
  filename: string;
  page_number: number | null;
  heading: string | null;
}

export interface FaqCluster {
  representative: string;
  occurrence_count: number;
  document_count: number;
  variants: string[];
  sources: FaqSource[];
}

export interface FaqGenerateResponse {
  question_count: number;
  document_count: number;
  clusters: FaqCluster[];
}

export function generateFaqs(input: {
  documentIds: string[];
  minOccurrences: number;
}): Promise<FaqGenerateResponse> {
  return postJson<FaqGenerateResponse>("/faq/generate", {
    document_ids: input.documentIds,
    min_occurrences: input.minOccurrences,
  });
}
