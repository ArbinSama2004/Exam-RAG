import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentSummary } from "../services/api";
import { renderWithQuery } from "../test/render";
import { DocumentList } from "./DocumentList";

function document(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    id: "doc-1",
    filename: "notes.pdf",
    document_type: "PDF",
    purpose: "STUDY_MATERIAL",
    status: "READY",
    size_bytes: 2048,
    chunk_count: 7,
    created_at: "2026-08-16T09:00:00Z",
    updated_at: "2026-08-16T09:00:00Z",
    ...overrides,
  };
}

function mockDocuments(documents: DocumentSummary[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => documents }),
  );
}

describe("DocumentList", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("invites a first upload when there is nothing yet", async () => {
    mockDocuments([]);

    renderWithQuery(<DocumentList />);

    expect(await screen.findByText(/nothing uploaded yet/i)).toBeInTheDocument();
  });

  it("shows each document with its status and chunk count", async () => {
    mockDocuments([document({ filename: "networking.pdf", chunk_count: 7 })]);

    renderWithQuery(<DocumentList />);

    const row = (await screen.findByText("networking.pdf")).closest("tr");
    expect(row).toHaveTextContent("Ready");
    expect(row).toHaveTextContent("7");
    expect(row).toHaveTextContent("2 KB");
  });

  it("labels both purposes readably", async () => {
    mockDocuments([
      document({ id: "a", filename: "study.pdf", purpose: "STUDY_MATERIAL" }),
      document({ id: "b", filename: "paper.pdf", purpose: "PAST_PAPER" }),
    ]);

    renderWithQuery(<DocumentList />);

    expect((await screen.findByText("study.pdf")).closest("tr")).toHaveTextContent(
      "Study material",
    );
    expect(screen.getByText("paper.pdf").closest("tr")).toHaveTextContent("Past paper");
  });

  it("shows a document that is still processing", async () => {
    mockDocuments([document({ status: "PROCESSING", chunk_count: 0 })]);

    renderWithQuery(<DocumentList />);

    expect(await screen.findByText("Processing")).toBeInTheDocument();
  });

  it("shows a failed document", async () => {
    mockDocuments([document({ status: "FAILED", chunk_count: 0 })]);

    renderWithQuery(<DocumentList />);

    expect(await screen.findByText("Failed")).toBeInTheDocument();
  });

  it("surfaces an unreachable backend", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Failed to fetch")));

    renderWithQuery(<DocumentList />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to fetch");
  });
});
