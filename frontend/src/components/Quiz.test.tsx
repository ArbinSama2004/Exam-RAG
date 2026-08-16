import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnswerResult, QuizPublic, QuizResult } from "../services/api";
import { renderWithQuery } from "../test/render";
import { Quiz } from "./Quiz";

const quiz: QuizPublic = {
  id: "quiz-1",
  difficulty: "MEDIUM",
  topic: null,
  question_count: 2,
  created_at: "2026-08-16T09:00:00Z",
  questions: [
    {
      id: "q1",
      position: 0,
      question: "Which protocol provides reliable transport?",
      options: ["HTTP", "IP", "TCP", "ARP"],
    },
    {
      id: "q2",
      position: 1,
      question: "What does IP guarantee?",
      options: ["Ordering", "Delivery", "Encryption", "Nothing by itself"],
    },
  ],
};

function answerResult(overrides: Partial<AnswerResult> = {}): AnswerResult {
  return {
    question_id: "q1",
    selected_index: 2,
    correct_index: 2,
    is_correct: true,
    explanation: "TCP retransmits lost segments.",
    source: "networking.pdf, p. 1 — Transport Layer",
    ...overrides,
  };
}

const result: QuizResult = {
  quiz_id: "quiz-1",
  score: 1,
  total: 2,
  correct: 1,
  incorrect: 1,
  unanswered: 0,
  submitted_at: "2026-08-16T09:10:00Z",
  questions: [
    {
      id: "q1",
      position: 0,
      question: "Which protocol provides reliable transport?",
      options: ["HTTP", "IP", "TCP", "ARP"],
      correct_index: 2,
      explanation: "TCP retransmits lost segments.",
      source: "networking.pdf, p. 1",
      selected_index: 2,
      is_correct: true,
    },
    {
      id: "q2",
      position: 1,
      question: "What does IP guarantee?",
      options: ["Ordering", "Delivery", "Encryption", "Nothing by itself"],
      correct_index: 3,
      explanation: "IP is best-effort.",
      source: "networking.pdf, p. 2",
      selected_index: 0,
      is_correct: false,
    },
  ],
};

/** Route each endpoint to a canned response. */
function mockApi(overrides: { answer?: AnswerResult; result?: QuizResult } = {}) {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => {
    const body = url.endsWith("/submit")
      ? (overrides.result ?? result)
      : (overrides.answer ?? answerResult());
    return { ok: true, status: 200, json: async () => body };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Quiz", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the first question and its position", () => {
    mockApi();
    renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    expect(screen.getByText("Question 1 / 2")).toBeInTheDocument();
    expect(screen.getByText(/Which protocol provides reliable/)).toBeInTheDocument();
  });

  it("does not reveal the correct answer before one is submitted", () => {
    mockApi();
    const { container } = renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    // The quiz object itself carries no key, and nothing marks an option.
    expect(container.querySelector(".choice--correct")).toBeNull();
    expect(container.textContent).not.toContain("retransmits");
  });

  it("cannot submit until an option is chosen", async () => {
    mockApi();
    renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    const button = screen.getByRole("button", { name: /submit answer/i });
    expect(button).toBeDisabled();

    await userEvent.click(screen.getByLabelText("TCP"));
    expect(button).toBeEnabled();
  });

  it("sends the chosen option to the backend", async () => {
    const fetchMock = mockApi();
    renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    await userEvent.click(screen.getByLabelText("TCP"));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/quizzes/quiz-1/answer");
    expect(JSON.parse(init.body)).toEqual({ question_id: "q1", selected_index: 2 });
  });

  it("confirms a correct answer and shows the explanation and source", async () => {
    mockApi();
    renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    await userEvent.click(screen.getByLabelText("TCP"));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));

    expect(await screen.findByText(/✓ Correct/)).toBeInTheDocument();
    expect(screen.getByText(/retransmits lost segments/)).toBeInTheDocument();
    expect(screen.getByText(/Transport Layer/)).toBeInTheDocument();
  });

  it("names the correct option when the answer is wrong", async () => {
    mockApi({ answer: answerResult({ selected_index: 0, is_correct: false }) });
    renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    await userEvent.click(screen.getByLabelText("HTTP"));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));

    expect(await screen.findByText(/✗ Incorrect — the answer is TCP/)).toBeInTheDocument();
  });

  it("locks the options once answered", async () => {
    mockApi();
    renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    await userEvent.click(screen.getByLabelText("TCP"));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));

    await screen.findByText(/✓ Correct/);
    expect(screen.getByLabelText("HTTP")).toBeDisabled();
  });

  it("moves to the next question", async () => {
    mockApi();
    renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    await userEvent.click(screen.getByLabelText("TCP"));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await userEvent.click(await screen.findByRole("button", { name: /next/i }));

    expect(screen.getByText("Question 2 / 2")).toBeInTheDocument();
    expect(screen.getByText(/What does IP guarantee/)).toBeInTheDocument();
  });

  it("offers to finish on the last question", async () => {
    mockApi();
    renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    await userEvent.click(screen.getByLabelText("TCP"));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await userEvent.click(await screen.findByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByLabelText("Ordering"));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));

    expect(await screen.findByRole("button", { name: /finish quiz/i })).toBeInTheDocument();
  });

  it("shows the score after finishing", async () => {
    mockApi();
    renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    await userEvent.click(screen.getByLabelText("TCP"));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await userEvent.click(await screen.findByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByLabelText("Ordering"));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await userEvent.click(await screen.findByRole("button", { name: /finish quiz/i }));

    expect(await screen.findByText("Score: 1 / 2")).toBeInTheDocument();
  });

  it("surfaces a backend error when answering fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: async () => ({ detail: "This question has already been answered." }),
      }),
    );
    renderWithQuery(<Quiz quiz={quiz} onFinished={vi.fn()} />);

    await userEvent.click(screen.getByLabelText("TCP"));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already been answered");
  });
});
