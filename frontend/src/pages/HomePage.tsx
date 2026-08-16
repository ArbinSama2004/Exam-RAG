import { useState } from "react";

import { BackendStatus } from "../components/BackendStatus";
import { DocumentList } from "../components/DocumentList";
import { FaqGenerator } from "../components/FaqGenerator";
import { IngestionProgress } from "../components/IngestionProgress";
import { Quiz } from "../components/Quiz";
import { QuizSetup } from "../components/QuizSetup";
import { RetrievalComparison } from "../components/RetrievalComparison";
import { UploadForm } from "../components/UploadForm";
import type { QuizPublic } from "../services/api";

type Tab = "documents" | "mcq" | "retrieval" | "faq";

const TABS: { id: Tab; label: string }[] = [
  { id: "documents", label: "Documents" },
  { id: "mcq", label: "MCQ generator" },
  { id: "retrieval", label: "Retrieval comparison" },
  { id: "faq", label: "Past paper FAQ" },
];

/** Application shell. */
export function HomePage() {
  const [tab, setTab] = useState<Tab>("documents");
  const [active, setActive] = useState<{ id: string; filename: string } | null>(null);
  const [quiz, setQuiz] = useState<QuizPublic | null>(null);

  return (
    <main className="app">
      <header className="app__header">
        <h1>ExamRAG</h1>
        <p className="subtitle">RAG-powered exam preparation assistant</p>
        <BackendStatus />
      </header>

      <nav className="tabs" aria-label="Sections">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={`tab${tab === entry.id ? " tab--active" : ""}`}
            aria-current={tab === entry.id ? "page" : undefined}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </nav>

      {tab === "documents" && (
        <>
          <UploadForm
            onUploaded={(response) =>
              setActive({ id: response.document.id, filename: response.document.filename })
            }
          />
          {active && <IngestionProgress documentId={active.id} filename={active.filename} />}
          <DocumentList />
        </>
      )}

      {tab === "mcq" &&
        (quiz ? (
          <Quiz quiz={quiz} onFinished={() => setQuiz(null)} />
        ) : (
          <QuizSetup onGenerated={setQuiz} />
        ))}

      {tab === "retrieval" && <RetrievalComparison />}

      {tab === "faq" && <FaqGenerator />}
    </main>
  );
}
