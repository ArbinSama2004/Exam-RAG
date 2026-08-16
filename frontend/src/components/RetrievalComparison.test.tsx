import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentSummary, RetrievalComparison as Comparison } from "../services/api";
import { renderWithQuery } from "../test/render";
import { RetrievalComparison } from "./RetrievalComparison";

const document_: DocumentSummary = {
  id: "doc-1",
  filename: "networking.pdf",
  document_type: "PDF",
  purpose: "STUDY_MATERIAL",
  status: "READY",
  size_bytes: 2048,
  chunk_count: 12,
  created_at: "2026-08-16T09:00:00Z",
  updated_at: "2026-08-16T09:00:00Z",
};

function chunk(content: string, rank: number) {
  return {
    chunk_id: `chunk-${content}`,
    document_id: "doc-1",
    filename: "networking.pdf",
    content,
    score: 1 / rank,
    rank,
    page_number: rank,
    heading: "Transport Layer",
    source: `networking.pdf, p. ${rank} — Transport Layer`,
  };
}

const comparison: Comparison = {
  query: "TCP",
  vector: [chunk("vector result", 1)],
  keyword: [chunk("keyword result", 1)],
  hybrid: [chunk("vector result", 1), chunk("keyword result", 2)],
  hybrid_reranked: [chunk("reranked result", 1)],
};

function mockApi(documents: DocumentSummary[] = [document_]) {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => (url.includes("/retrieval/compare") ? comparison : documents),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("RetrievalComparison", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("says when there is nothing to search", async () => {
    mockApi([]);
    renderWithQuery(<RetrievalComparison />);

    expect(await screen.findByText(/no study material is ready/i)).toBeInTheDocument();
  });

  it("cannot compare without a query", async () => {
    mockApi();
    renderWithQuery(<RetrievalComparison />);

    expect(await screen.findByRole("button", { name: /compare/i })).toBeDisabled();
  });

  it("shows all four retrieval methods", async () => {
    mockApi();
    renderWithQuery(<RetrievalComparison />);

    await userEvent.type(await screen.findByLabelText(/query/i), "TCP");
    await userEvent.click(screen.getByRole("button", { name: /compare/i }));

    await screen.findByText(/Vector only/);
    const headings = screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent);
    expect(headings).toEqual([
      "Vector only (1)",
      "Keyword only (1)",
      "Hybrid (2)",
      "Hybrid + reranking (1)",
    ]);
  });

  it("shows each method's own results with rank and source", async () => {
    mockApi();
    renderWithQuery(<RetrievalComparison />);

    await userEvent.type(await screen.findByLabelText(/query/i), "TCP");
    await userEvent.click(screen.getByRole("button", { name: /compare/i }));

    // "vector result" appears in both the vector and hybrid columns, which is
    // the point: fusion carries results through.
    expect(await screen.findAllByText(/vector result/)).toHaveLength(2);
    expect(screen.getAllByText(/keyword result/)).toHaveLength(2);
    expect(screen.getByText(/reranked result/)).toBeInTheDocument();
    expect(screen.getAllByText(/#1 · score/).length).toBeGreaterThan(0);
  });

  it("sends the query and selected documents", async () => {
    const fetchMock = mockApi();
    renderWithQuery(<RetrievalComparison />);

    await userEvent.click(await screen.findByLabelText(/networking\.pdf/));
    await userEvent.type(screen.getByLabelText(/query/i), "TCP");
    await userEvent.click(screen.getByRole("button", { name: /compare/i }));

    const call = fetchMock.mock.calls.find(([url]) => url.includes("/retrieval/compare"));
    expect(JSON.parse(call![1].body)).toEqual({ query: "TCP", document_ids: ["doc-1"] });
  });

  it("surfaces a retrieval failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: string) => {
        if (url.includes("/retrieval/compare")) {
          return { ok: false, status: 503, json: async () => ({ detail: "Reranker unavailable" }) };
        }
        return { ok: true, status: 200, json: async () => [document_] };
      }),
    );
    renderWithQuery(<RetrievalComparison />);

    await userEvent.type(await screen.findByLabelText(/query/i), "TCP");
    await userEvent.click(screen.getByRole("button", { name: /compare/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Reranker unavailable");
  });
});
