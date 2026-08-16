import { BackendStatus } from "../components/BackendStatus";

/**
 * Application shell. Document upload, the MCQ generator and the FAQ generator
 * are added in the phases that implement them.
 */
export function HomePage() {
  return (
    <main className="app">
      <h1>ExamRAG</h1>
      <p className="subtitle">RAG-powered exam preparation assistant</p>
      <BackendStatus />
    </main>
  );
}
