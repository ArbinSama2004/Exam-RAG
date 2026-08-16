import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  type RetrievalComparison as Comparison,
  type RetrievedChunk,
  compareRetrieval,
  fetchDocuments,
} from "../services/api";

const METHODS: { key: keyof Omit<Comparison, "query">; label: string; hint: string }[] = [
  { key: "vector", label: "Vector only", hint: "Semantic similarity through pgvector" },
  { key: "keyword", label: "Keyword only", hint: "PostgreSQL full-text search" },
  { key: "hybrid", label: "Hybrid", hint: "Both, combined with Reciprocal Rank Fusion" },
  {
    key: "hybrid_reranked",
    label: "Hybrid + reranking",
    hint: "Fused candidates reordered by a cross-encoder — what the model actually sees",
  },
];

/**
 * Run one query through every retrieval method and show the results side by
 * side, so the differences can be inspected rather than taken on trust.
 */
export function RetrievalComparison() {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);

  const documents = useQuery({
    queryKey: ["documents", "STUDY_MATERIAL"],
    queryFn: () => fetchDocuments("STUDY_MATERIAL"),
  });

  const compare = useMutation({
    mutationFn: () => compareRetrieval(query, selected),
  });

  const ready = (documents.data ?? []).filter((document) => document.status === "READY");

  return (
    <section className="card">
      <h2>Retrieval comparison</h2>
      <p className="field__hint">
        See what each retrieval method returns for the same query. All four use the same
        components as the main pipeline.
      </p>

      {ready.length === 0 ? (
        <p className="empty">No study material is ready yet.</p>
      ) : (
        <>
          <fieldset className="field">
            <legend className="field__label">Documents</legend>
            {ready.map((document) => (
              <label key={document.id} className="choice">
                <input
                  type="checkbox"
                  checked={selected.includes(document.id)}
                  onChange={() =>
                    setSelected((current) =>
                      current.includes(document.id)
                        ? current.filter((value) => value !== document.id)
                        : [...current, document.id],
                    )
                  }
                />
                <span>{document.filename}</span>
              </label>
            ))}
            <span className="field__hint">Select none to search everything.</span>
          </fieldset>

          <label className="field">
            <span className="field__label">Query</span>
            <input
              type="text"
              value={query}
              placeholder="e.g. how does TCP guarantee delivery?"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>

          <button
            type="button"
            disabled={!query.trim() || compare.isPending}
            onClick={() => compare.mutate()}
          >
            {compare.isPending ? "Retrieving…" : "Compare"}
          </button>

          {compare.isError && (
            <p className="status status--error" role="alert">
              {compare.error instanceof Error ? compare.error.message : "Retrieval failed"}
            </p>
          )}

          {compare.data && (
            <div className="comparison">
              {METHODS.map((method) => (
                <MethodColumn
                  key={method.key}
                  label={method.label}
                  hint={method.hint}
                  chunks={compare.data[method.key]}
                />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function MethodColumn({
  label,
  hint,
  chunks,
}: {
  label: string;
  hint: string;
  chunks: RetrievedChunk[];
}) {
  return (
    <div className="comparison__column">
      <h3>
        {label} <span className="field__hint">({chunks.length})</span>
      </h3>
      <p className="field__hint">{hint}</p>
      {chunks.length === 0 && <p className="empty">No results.</p>}
      <ol className="comparison__results">
        {chunks.slice(0, 6).map((chunk) => (
          <li key={chunk.chunk_id}>
            <p className="field__hint">
              #{chunk.rank} · score {chunk.score.toFixed(3)} · {chunk.source}
            </p>
            <p className="comparison__text">{chunk.content.slice(0, 240)}…</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
