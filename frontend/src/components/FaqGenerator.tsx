import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  type FaqCluster,
  type FaqGenerateResponse,
  fetchDocuments,
  generateFaqs,
} from "../services/api";

const MIN_OCCURRENCES_OPTIONS = [1, 2, 3, 5];

/**
 * Find exam questions that recur across past papers, and how often.
 *
 * No model is involved — extraction is heuristic and grouping reuses the same
 * embeddings retrieval uses — so results come back in well under a second.
 */
export function FaqGenerator() {
  const [selected, setSelected] = useState<string[]>([]);
  const [minOccurrences, setMinOccurrences] = useState(2);

  const documents = useQuery({
    queryKey: ["documents", "PAST_PAPER"],
    queryFn: () => fetchDocuments("PAST_PAPER"),
  });

  const generate = useMutation({
    mutationFn: () => generateFaqs({ documentIds: selected, minOccurrences }),
  });

  const ready = (documents.data ?? []).filter((document) => document.status === "READY");

  function toggle(id: string) {
    setSelected((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  }

  return (
    <section className="card">
      <h2>Past paper FAQ</h2>
      <p className="field__hint">
        Finds questions that come up again in a different year or a different paper, and ranks
        them by how often they repeat.
      </p>

      {documents.isPending && <p className="status">Loading past papers…</p>}

      {documents.data && ready.length === 0 && (
        <p className="empty">
          No past papers are ready yet. Upload one under &ldquo;Documents&rdquo; with purpose
          &ldquo;Past paper&rdquo;.
        </p>
      )}

      {ready.length > 0 && (
        <>
          <fieldset className="field">
            <legend className="field__label">Past papers</legend>
            {ready.map((document) => (
              <label key={document.id} className="choice">
                <input
                  type="checkbox"
                  checked={selected.includes(document.id)}
                  onChange={() => toggle(document.id)}
                />
                <span>{document.filename}</span>
              </label>
            ))}
            <span className="field__hint">Select none to search every past paper.</span>
          </fieldset>

          <label className="field">
            <span className="field__label">Minimum repeats</span>
            <select
              value={minOccurrences}
              onChange={(event) => setMinOccurrences(Number(event.target.value))}
            >
              {MIN_OCCURRENCES_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value === 1 ? "Show every question" : `Appears ${value}+ times`}
                </option>
              ))}
            </select>
          </label>

          <button type="button" disabled={generate.isPending} onClick={() => generate.mutate()}>
            {generate.isPending ? "Finding repeats…" : "Find repeated questions"}
          </button>

          {generate.isError && (
            <p className="status status--error" role="alert">
              {generate.error instanceof Error ? generate.error.message : "FAQ generation failed"}
            </p>
          )}

          {generate.data && <FaqResults data={generate.data} />}
        </>
      )}
    </section>
  );
}

function FaqResults({ data }: { data: FaqGenerateResponse }) {
  return (
    <div className="faq-results">
      <p className="field__hint">
        Found {data.question_count} question{data.question_count === 1 ? "" : "s"} across{" "}
        {data.document_count} paper{data.document_count === 1 ? "" : "s"}.
      </p>

      {data.clusters.length === 0 ? (
        <p className="empty">Nothing repeats at that threshold yet.</p>
      ) : (
        <ol className="faq-list">
          {data.clusters.map((cluster, index) => (
            <FaqItem key={index} cluster={cluster} />
          ))}
        </ol>
      )}
    </div>
  );
}

function FaqItem({ cluster }: { cluster: FaqCluster }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <li className="faq-item">
      <div className="faq-item__header">
        <span className="badge badge--ready">× {cluster.occurrence_count}</span>
        <p className="faq-item__question">{cluster.representative}</p>
      </div>
      <p className="field__hint">
        Appeared in {cluster.document_count} paper{cluster.document_count === 1 ? "" : "s"}
      </p>

      <button type="button" onClick={() => setExpanded((value) => !value)}>
        {expanded ? "Hide sources" : "Show sources"}
      </button>

      {expanded && (
        <div className="faq-item__detail">
          <ul className="faq-item__sources">
            {cluster.sources.map((source, index) => (
              <li key={index}>
                {source.filename}
                {source.page_number != null ? `, p. ${source.page_number}` : ""}
                {source.heading ? ` — ${source.heading}` : ""}
              </li>
            ))}
          </ul>
          {cluster.variants.length > 0 && (
            <>
              <p className="field__label">Other phrasings</p>
              <ul className="faq-item__variants">
                {cluster.variants.map((variant, index) => (
                  <li key={index}>{variant}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </li>
  );
}
