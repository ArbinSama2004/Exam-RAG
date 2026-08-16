import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { type IngestionStage, fetchIngestionStatus, isTerminal } from "../services/api";

/** The stages a document passes through, in order, with what to call each one. */
const STAGES: { stage: IngestionStage; label: string }[] = [
  { stage: "QUEUED", label: "Uploading" },
  { stage: "LOADING", label: "Reading the file" },
  { stage: "CLEANING", label: "Converting to Markdown" },
  { stage: "CHUNKING", label: "Chunking" },
  { stage: "EMBEDDING", label: "Generating embeddings" },
  { stage: "INDEXING", label: "Indexing" },
  { stage: "COMPLETED", label: "Ready" },
];

/** How often to ask the backend for progress while a document is processing. */
const POLL_INTERVAL_MS = 1000;

interface Props {
  documentId: string;
  filename: string;
}

/**
 * Follow one document through ingestion.
 *
 * Polling stops as soon as the document reaches READY or FAILED, so a finished
 * upload does not keep asking the backend.
 */
export function IngestionProgress({ documentId, filename }: Props) {
  const queryClient = useQueryClient();

  const { data, isPending, isError, error } = useQuery({
    queryKey: ["ingestion-status", documentId],
    queryFn: () => fetchIngestionStatus(documentId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isTerminal(status) ? false : POLL_INTERVAL_MS;
    },
    // Keep polling when the tab is in the background. Otherwise a user who
    // switches away during a long PDF comes back to a frozen progress list,
    // since this app also disables refetch-on-focus.
    refetchIntervalInBackground: true,
  });

  // The document list shows status and chunk count, so refresh it once this
  // document settles.
  useEffect(() => {
    if (data && isTerminal(data.status)) {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  }, [data, queryClient]);

  if (isPending) {
    return (
      <section className="card">
        <h2>Processing {filename}</h2>
        <p className="status">Starting…</p>
      </section>
    );
  }

  if (isError) {
    return (
      <section className="card">
        <h2>Processing {filename}</h2>
        <p className="status status--error" role="alert">
          {error instanceof Error ? error.message : "Could not read the status"}
        </p>
      </section>
    );
  }

  const currentIndex = STAGES.findIndex((entry) => entry.stage === data.stage);
  const failed = data.status === "FAILED";
  const ready = data.status === "READY";

  return (
    <section className="card">
      <h2>Processing {filename}</h2>

      <ol className="stages">
        {STAGES.map((entry, index) => {
          const done = ready || index < currentIndex;
          const active = !ready && !failed && index === currentIndex;
          return (
            <li
              key={entry.stage}
              className={`stage${done ? " stage--done" : ""}${active ? " stage--active" : ""}`}
              aria-current={active ? "step" : undefined}
            >
              <span className="stage__marker" aria-hidden="true">
                {done ? "✓" : active ? "•" : "○"}
              </span>
              {entry.label}
            </li>
          );
        })}
      </ol>

      {ready && (
        <p className="status status--ok" role="status">
          Ready — {data.chunk_count} chunk{data.chunk_count === 1 ? "" : "s"} indexed and
          available for retrieval.
        </p>
      )}

      {failed && (
        <p className="status status--error" role="alert">
          Processing failed: {data.error_message ?? "unknown error"}
        </p>
      )}
    </section>
  );
}
