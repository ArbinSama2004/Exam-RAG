import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithQuery } from "../test/render";
import { UploadForm } from "./UploadForm";

const uploaded = {
  document: {
    id: "doc-1",
    filename: "notes.md",
    document_type: "MARKDOWN",
    purpose: "STUDY_MATERIAL",
    status: "UPLOADED",
    size_bytes: 12,
    chunk_count: 0,
    created_at: "2026-08-16T09:00:00Z",
    updated_at: "2026-08-16T09:00:00Z",
  },
  job_id: "job-1",
  reused: false,
};

function markdownFile(name = "notes.md") {
  return new File(["# Notes"], name, { type: "text/markdown" });
}

function mockFetch(response: object, ok = true, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => response,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("UploadForm", () => {
  beforeEach(() => {
    mockFetch(uploaded);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("cannot be submitted before a file and a purpose are chosen", async () => {
    renderWithQuery(<UploadForm onUploaded={vi.fn()} />);

    const button = screen.getByRole("button", { name: /upload/i });
    expect(button).toBeDisabled();

    await userEvent.upload(screen.getByLabelText(/file/i), markdownFile());
    // A file alone is not enough: the purpose decides how the document is used.
    expect(button).toBeDisabled();

    await userEvent.click(screen.getByLabelText(/study material/i));
    expect(button).toBeEnabled();
  });

  it("offers both document purposes", () => {
    renderWithQuery(<UploadForm onUploaded={vi.fn()} />);

    expect(screen.getByLabelText(/study material/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/past paper/i)).toBeInTheDocument();
  });

  it("posts the file and the chosen purpose", async () => {
    const fetchMock = mockFetch(uploaded);
    renderWithQuery(<UploadForm onUploaded={vi.fn()} />);

    await userEvent.upload(screen.getByLabelText(/file/i), markdownFile());
    await userEvent.click(screen.getByLabelText(/past paper/i));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/documents");
    expect(init.method).toBe("POST");
    const body = init.body as FormData;
    expect(body.get("purpose")).toBe("PAST_PAPER");
    expect((body.get("file") as File).name).toBe("notes.md");
  });

  it("reports the uploaded document to its parent", async () => {
    const onUploaded = vi.fn();
    renderWithQuery(<UploadForm onUploaded={onUploaded} />);

    await userEvent.upload(screen.getByLabelText(/file/i), markdownFile());
    await userEvent.click(screen.getByLabelText(/study material/i));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(uploaded));
  });

  it("only offers the file types the backend accepts", () => {
    renderWithQuery(<UploadForm onUploaded={vi.fn()} />);

    // The picker filters unsupported files before a request is ever made.
    expect(screen.getByLabelText(/file/i)).toHaveAttribute(
      "accept",
      ".pdf,.docx,.md,.markdown,.txt",
    );
  });

  it("shows the backend's message when the upload is rejected", async () => {
    mockFetch({ detail: "'notes.md' is 60.0 MB, over the 50 MB limit." }, false, 413);
    renderWithQuery(<UploadForm onUploaded={vi.fn()} />);

    await userEvent.upload(screen.getByLabelText(/file/i), markdownFile());
    await userEvent.click(screen.getByLabelText(/study material/i));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("over the 50 MB limit");
  });

  it("says when an unchanged file was reused instead of reprocessed", async () => {
    mockFetch({ ...uploaded, reused: true });
    renderWithQuery(<UploadForm onUploaded={vi.fn()} />);

    await userEvent.upload(screen.getByLabelText(/file/i), markdownFile());
    await userEvent.click(screen.getByLabelText(/study material/i));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/already uploaded/i);
  });
});
