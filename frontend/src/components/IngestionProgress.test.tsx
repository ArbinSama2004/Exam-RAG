import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IngestionStage, IngestionStatus, ProcessingStatus } from "../services/api";
import { renderWithQuery } from "../test/render";
import { IngestionProgress } from "./IngestionProgress";

function status(
  overrides: Partial<IngestionStatus> & { status: ProcessingStatus; stage: IngestionStage },
): IngestionStatus {
  return {
    document_id: "doc-1",
    job_id: "job-1",
    chunk_count: 0,
    error_message: null,
    started_at: null,
    finished_at: null,
    updated_at: "2026-08-16T09:00:00Z",
    ...overrides,
  };
}

/** Serve a sequence of statuses, repeating the last one once exhausted. */
function mockPolling(sequence: IngestionStatus[]) {
  let call = 0;
  const fetchMock = vi.fn().mockImplementation(async () => {
    const body = sequence[Math.min(call, sequence.length - 1)];
    call += 1;
    return { ok: true, status: 200, json: async () => body };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("IngestionProgress", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("marks the current stage while processing", async () => {
    mockPolling([status({ status: "PROCESSING", stage: "CHUNKING" })]);

    renderWithQuery(<IngestionProgress documentId="doc-1" filename="notes.pdf" />);

    const current = await screen.findByText("Chunking");
    expect(current).toHaveAttribute("aria-current", "step");
    // Earlier stages are already behind it.
    expect(screen.getByText("Reading the file")).not.toHaveAttribute("aria-current");
  });

  it("shows the filename being processed", async () => {
    mockPolling([status({ status: "PROCESSING", stage: "EMBEDDING" })]);

    renderWithQuery(<IngestionProgress documentId="doc-1" filename="networking.pdf" />);

    expect(await screen.findByText(/networking\.pdf/)).toBeInTheDocument();
  });

  it("reports the chunk count once the document is ready", async () => {
    mockPolling([status({ status: "READY", stage: "COMPLETED", chunk_count: 12 })]);

    renderWithQuery(<IngestionProgress documentId="doc-1" filename="notes.pdf" />);

    expect(await screen.findByRole("status")).toHaveTextContent("12 chunks");
  });

  it("uses the singular for a single chunk", async () => {
    mockPolling([status({ status: "READY", stage: "COMPLETED", chunk_count: 1 })]);

    renderWithQuery(<IngestionProgress documentId="doc-1" filename="notes.pdf" />);

    expect(await screen.findByRole("status")).toHaveTextContent("1 chunk indexed");
  });

  it("shows the failure message from the backend", async () => {
    mockPolling([
      status({
        status: "FAILED",
        stage: "EMBEDDING",
        error_message: "EmbeddingError: model unavailable",
      }),
    ]);

    renderWithQuery(<IngestionProgress documentId="doc-1" filename="notes.pdf" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("model unavailable");
  });

  it("keeps polling until the document reaches a terminal status", async () => {
    const fetchMock = mockPolling([
      status({ status: "PROCESSING", stage: "CHUNKING" }),
      status({ status: "PROCESSING", stage: "EMBEDDING" }),
      status({ status: "READY", stage: "COMPLETED", chunk_count: 3 }),
    ]);

    renderWithQuery(<IngestionProgress documentId="doc-1" filename="notes.pdf" />);

    await screen.findByRole("status", {}, { timeout: 5000 });
    const callsWhenReady = fetchMock.mock.calls.length;
    expect(callsWhenReady).toBeGreaterThan(1);

    // Polling must stop once the document is READY, not keep asking forever.
    await new Promise((resolve) => setTimeout(resolve, 1500));
    expect(fetchMock.mock.calls.length).toBe(callsWhenReady);
  }, 10000);

  it("surfaces an unreachable backend", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Failed to fetch")));

    renderWithQuery(<IngestionProgress documentId="doc-1" filename="notes.pdf" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to fetch");
  });
});
