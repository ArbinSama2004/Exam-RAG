import { useQuery } from "@tanstack/react-query";

import { type DocumentSummary, type ProcessingStatus, fetchDocuments } from "../services/api";

const STATUS_LABELS: Record<ProcessingStatus, string> = {
  UPLOADED: "Queued",
  PROCESSING: "Processing",
  READY: "Ready",
  FAILED: "Failed",
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Documents already uploaded, newest first. */
export function DocumentList() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["documents"],
    queryFn: () => fetchDocuments(),
  });

  return (
    <section className="card">
      <h2>Your documents</h2>

      {isPending && <p className="status">Loading…</p>}

      {isError && (
        <p className="status status--error" role="alert">
          {error instanceof Error ? error.message : "Could not load documents"}
        </p>
      )}

      {data && data.length === 0 && (
        <p className="empty">Nothing uploaded yet. Add a document above to get started.</p>
      )}

      {data && data.length > 0 && (
        <table className="documents">
          <thead>
            <tr>
              <th scope="col">File</th>
              <th scope="col">Purpose</th>
              <th scope="col">Status</th>
              <th scope="col">Chunks</th>
              <th scope="col">Size</th>
            </tr>
          </thead>
          <tbody>
            {data.map((document: DocumentSummary) => (
              <tr key={document.id}>
                <td>{document.filename}</td>
                <td>{document.purpose === "PAST_PAPER" ? "Past paper" : "Study material"}</td>
                <td>
                  <span className={`badge badge--${document.status.toLowerCase()}`}>
                    {STATUS_LABELS[document.status]}
                  </span>
                </td>
                <td>{document.chunk_count}</td>
                <td>{formatSize(document.size_bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
