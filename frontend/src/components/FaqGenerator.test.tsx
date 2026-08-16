import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentSummary, FaqGenerateResponse } from "../services/api";
import { renderWithQuery } from "../test/render";
import { FaqGenerator } from "./FaqGenerator";

const pastPaper: DocumentSummary = {
  id: "paper-1",
  filename: "2023-exam.pdf",
  document_type: "PDF",
  purpose: "PAST_PAPER",
  status: "READY",
  size_bytes: 4096,
  chunk_count: 8,
  created_at: "2026-08-16T09:00:00Z",
  updated_at: "2026-08-16T09:00:00Z",
};

const response: FaqGenerateResponse = {
  question_count: 5,
  document_count: 2,
  clusters: [
    {
      representative: "Explain the seven layers of the OSI model.",
      occurrence_count: 3,
      document_count: 2,
      variants: ["Describe the OSI model's seven layers."],
      sources: [
        { document_id: "paper-1", filename: "2023-exam.pdf", page_number: 2, heading: "Section A" },
        { document_id: "paper-2", filename: "2024-exam.pdf", page_number: 1, heading: null },
      ],
    },
  ],
};

function mockApi(documents: DocumentSummary[] = [pastPaper]) {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => (url.includes("/faq/generate") ? response : documents),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("FaqGenerator", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("says when there are no past papers yet", async () => {
    mockApi([]);
    renderWithQuery(<FaqGenerator />);

    expect(await screen.findByText(/no past papers are ready/i)).toBeInTheDocument();
  });

  it("lists ready past papers as checkboxes", async () => {
    mockApi();
    renderWithQuery(<FaqGenerator />);

    expect(await screen.findByLabelText(/2023-exam\.pdf/)).toBeInTheDocument();
  });

  it("shows the ranked clusters after generating", async () => {
    mockApi();
    renderWithQuery(<FaqGenerator />);

    await userEvent.click(
      await screen.findByRole("button", { name: /find repeated questions/i }),
    );

    expect(await screen.findByText(/explain the seven layers of the osi model/i)).toBeInTheDocument();
    expect(screen.getByText("× 3")).toBeInTheDocument();
    expect(screen.getByText(/found 5 questions across 2 papers/i)).toBeInTheDocument();
  });

  it("reveals sources and variants on demand", async () => {
    mockApi();
    renderWithQuery(<FaqGenerator />);

    await userEvent.click(
      await screen.findByRole("button", { name: /find repeated questions/i }),
    );
    await userEvent.click(await screen.findByRole("button", { name: /show sources/i }));

    expect(screen.getByText(/2023-exam\.pdf, p\. 2 — Section A/)).toBeInTheDocument();
    expect(screen.getByText(/describe the osi model's seven layers/i)).toBeInTheDocument();
  });

  it("sends the selected documents and minimum occurrences", async () => {
    const fetchMock = mockApi();
    renderWithQuery(<FaqGenerator />);

    await userEvent.click(await screen.findByLabelText(/2023-exam\.pdf/));
    await userEvent.selectOptions(await screen.findByLabelText(/minimum repeats/i), "1");
    await userEvent.click(screen.getByRole("button", { name: /find repeated questions/i }));

    const call = fetchMock.mock.calls.find(([url]) => url.includes("/faq/generate"));
    expect(JSON.parse(call![1].body)).toEqual({
      document_ids: ["paper-1"],
      min_occurrences: 1,
    });
  });

  it("surfaces a generation failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: string) => {
        if (url.includes("/faq/generate")) {
          return { ok: false, status: 500, json: async () => ({ detail: "Generation failed" }) };
        }
        return { ok: true, status: 200, json: async () => [pastPaper] };
      }),
    );
    renderWithQuery(<FaqGenerator />);

    await userEvent.click(
      await screen.findByRole("button", { name: /find repeated questions/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Generation failed");
  });

  it("says when nothing repeats at the chosen threshold", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: string) => ({
        ok: true,
        status: 200,
        json: async () =>
          url.includes("/faq/generate")
            ? { question_count: 1, document_count: 1, clusters: [] }
            : [pastPaper],
      })),
    );
    renderWithQuery(<FaqGenerator />);

    await userEvent.click(
      await screen.findByRole("button", { name: /find repeated questions/i }),
    );

    expect(await screen.findByText(/nothing repeats at that threshold/i)).toBeInTheDocument();
  });
});
