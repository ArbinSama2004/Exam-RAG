import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  ACCEPTED_EXTENSIONS,
  type DocumentPurpose,
  type UploadResponse,
  uploadDocument,
} from "../services/api";

const PURPOSES: { value: DocumentPurpose; label: string; hint: string }[] = [
  {
    value: "STUDY_MATERIAL",
    label: "Study material",
    hint: "Used for MCQ generation and RAG answers",
  },
  {
    value: "PAST_PAPER",
    label: "Past paper",
    hint: "Used for question extraction and FAQ analysis",
  },
];

interface Props {
  /** Called with the uploaded document so the page can follow its progress. */
  onUploaded: (response: UploadResponse) => void;
}

/**
 * Upload a document. The purpose is a required choice rather than a default,
 * because it decides whether the document can be used as answer evidence.
 */
export function UploadForm({ onUploaded }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [purpose, setPurpose] = useState<DocumentPurpose | "">("");
  const fileInput = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const upload = useMutation({
    mutationFn: ({ file, purpose }: { file: File; purpose: DocumentPurpose }) =>
      uploadDocument(file, purpose),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      onUploaded(response);
      setFile(null);
      setPurpose("");
      if (fileInput.current) {
        fileInput.current.value = "";
      }
    },
  });

  const canSubmit = file !== null && purpose !== "" && !upload.isPending;

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        if (file && purpose) {
          upload.mutate({ file, purpose });
        }
      }}
    >
      <h2>Upload a document</h2>

      <label className="field">
        <span className="field__label">File</span>
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPTED_EXTENSIONS}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <span className="field__hint">PDF, DOCX, Markdown or TXT</span>
      </label>

      <fieldset className="field">
        <legend className="field__label">Purpose</legend>
        {PURPOSES.map((option) => (
          <label key={option.value} className="choice">
            <input
              type="radio"
              name="purpose"
              value={option.value}
              checked={purpose === option.value}
              onChange={() => setPurpose(option.value)}
            />
            <span>
              {option.label}
              <span className="field__hint"> — {option.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <button type="submit" disabled={!canSubmit}>
        {upload.isPending ? "Uploading…" : "Upload"}
      </button>

      {upload.isError && (
        <p className="status status--error" role="alert">
          {upload.error instanceof Error ? upload.error.message : "Upload failed"}
        </p>
      )}

      {upload.isSuccess && upload.data.reused && (
        <p className="status status--ok" role="status">
          Already uploaded — reusing the existing document instead of processing it again.
        </p>
      )}
    </form>
  );
}
