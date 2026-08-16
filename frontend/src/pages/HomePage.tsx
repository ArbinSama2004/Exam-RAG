import { useState } from "react";

import { BackendStatus } from "../components/BackendStatus";
import { DocumentList } from "../components/DocumentList";
import { IngestionProgress } from "../components/IngestionProgress";
import { UploadForm } from "../components/UploadForm";

/**
 * Application shell. The MCQ generator and FAQ generator are added in the
 * phases that implement them.
 */
export function HomePage() {
  const [active, setActive] = useState<{ id: string; filename: string } | null>(null);

  return (
    <main className="app">
      <header className="app__header">
        <h1>ExamRAG</h1>
        <p className="subtitle">RAG-powered exam preparation assistant</p>
        <BackendStatus />
      </header>

      <UploadForm
        onUploaded={(response) =>
          setActive({ id: response.document.id, filename: response.document.filename })
        }
      />

      {active && <IngestionProgress documentId={active.id} filename={active.filename} />}

      <DocumentList />
    </main>
  );
}
