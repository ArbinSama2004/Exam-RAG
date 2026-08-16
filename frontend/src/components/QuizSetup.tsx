import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  type Difficulty,
  type QuizPublic,
  fetchDocuments,
  generateQuiz,
} from "../services/api";

const DIFFICULTIES: Difficulty[] = ["EASY", "MEDIUM", "HARD"];
const COUNTS = [5, 10, 15, 20];

interface Props {
  onGenerated: (quiz: QuizPublic) => void;
}

/** Choose documents and settings, then generate a quiz. */
export function QuizSetup({ onGenerated }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [count, setCount] = useState(10);
  const [difficulty, setDifficulty] = useState<Difficulty>("MEDIUM");
  const [topic, setTopic] = useState("");

  const documents = useQuery({
    queryKey: ["documents", "STUDY_MATERIAL"],
    queryFn: () => fetchDocuments("STUDY_MATERIAL"),
  });

  const generate = useMutation({
    mutationFn: () =>
      generateQuiz({
        documentIds: selected,
        count,
        difficulty,
        topic: topic.trim() || null,
      }),
    onSuccess: onGenerated,
  });

  // Only ready documents have chunks to retrieve from.
  const ready = (documents.data ?? []).filter((document) => document.status === "READY");

  function toggle(id: string) {
    setSelected((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  }

  return (
    <section className="card">
      <h2>MCQ generator</h2>

      {documents.isPending && <p className="status">Loading documents…</p>}

      {documents.data && ready.length === 0 && (
        <p className="empty">
          No study material is ready yet. Upload a document and wait for it to finish
          processing.
        </p>
      )}

      {ready.length > 0 && (
        <>
          <fieldset className="field">
            <legend className="field__label">Documents</legend>
            {ready.map((document) => (
              <label key={document.id} className="choice">
                <input
                  type="checkbox"
                  checked={selected.includes(document.id)}
                  onChange={() => toggle(document.id)}
                />
                <span>
                  {document.filename}
                  <span className="field__hint"> — {document.chunk_count} chunks</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div className="row">
            <label className="field">
              <span className="field__label">Number of questions</span>
              <select value={count} onChange={(event) => setCount(Number(event.target.value))}>
                {COUNTS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="field__label">Difficulty</span>
              <select
                value={difficulty}
                onChange={(event) => setDifficulty(event.target.value as Difficulty)}
              >
                {DIFFICULTIES.map((value) => (
                  <option key={value} value={value}>
                    {value.charAt(0) + value.slice(1).toLowerCase()}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="field">
            <span className="field__label">Topic</span>
            <input
              type="text"
              value={topic}
              placeholder="All topics"
              onChange={(event) => setTopic(event.target.value)}
            />
            <span className="field__hint">
              Leave empty to spread questions across every section of the selected documents.
            </span>
          </label>

          <button
            type="button"
            disabled={selected.length === 0 || generate.isPending}
            onClick={() => generate.mutate()}
          >
            {generate.isPending ? "Generating…" : "Generate MCQs"}
          </button>

          {generate.isPending && (
            <p className="status">
              The model is writing questions from your material. This can take a minute.
            </p>
          )}

          {generate.isError && (
            <p className="status status--error" role="alert">
              {generate.error instanceof Error ? generate.error.message : "Generation failed"}
            </p>
          )}
        </>
      )}
    </section>
  );
}
