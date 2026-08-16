import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import {
  type AnswerResult,
  type QuizPublic,
  type QuizResult,
  answerQuestion,
  submitQuiz,
} from "../services/api";
import { QuizReview } from "./QuizReview";

interface Props {
  quiz: QuizPublic;
  onFinished: () => void;
}

/**
 * Take a quiz, one question at a time.
 *
 * The correct answer is not in `quiz` — it arrives only in the response to
 * answering, which is what keeps it out of the browser until the user has
 * committed.
 */
export function Quiz({ quiz, onFinished }: Props) {
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [finalResult, setFinalResult] = useState<QuizResult | null>(null);

  const question = quiz.questions[index];
  const isLast = index === quiz.questions.length - 1;

  const answer = useMutation({
    mutationFn: (choice: number) => answerQuestion(quiz.id, question.id, choice),
    onSuccess: setResult,
  });

  const finish = useMutation({
    mutationFn: () => submitQuiz(quiz.id),
    onSuccess: setFinalResult,
  });

  if (finalResult) {
    return <QuizReview result={finalResult} onRestart={onFinished} />;
  }

  function next() {
    if (isLast) {
      finish.mutate();
      return;
    }
    setIndex((current) => current + 1);
    setSelected(null);
    setResult(null);
  }

  return (
    <section className="card">
      <h2>
        Question {index + 1} / {quiz.questions.length}
      </h2>

      <p className="question">{question.question}</p>

      <fieldset className="field" disabled={result !== null}>
        {question.options.map((option, optionIndex) => (
          <label key={option} className={`choice ${optionClass(optionIndex, result)}`}>
            <input
              type="radio"
              name={`question-${question.id}`}
              checked={selected === optionIndex}
              onChange={() => setSelected(optionIndex)}
            />
            <span>{option}</span>
          </label>
        ))}
      </fieldset>

      {result === null && (
        <button
          type="button"
          disabled={selected === null || answer.isPending}
          onClick={() => selected !== null && answer.mutate(selected)}
        >
          {answer.isPending ? "Checking…" : "Submit answer"}
        </button>
      )}

      {answer.isError && (
        <p className="status status--error" role="alert">
          {answer.error instanceof Error ? answer.error.message : "Could not submit"}
        </p>
      )}

      {result && (
        <div className="feedback" role="status">
          <p className={result.is_correct ? "status status--ok" : "status status--error"}>
            {result.is_correct
              ? "✓ Correct"
              : `✗ Incorrect — the answer is ${question.options[result.correct_index]}`}
          </p>
          <p className="explanation">{result.explanation}</p>
          <p className="field__hint">Source: {result.source}</p>
          <button type="button" onClick={next} disabled={finish.isPending}>
            {isLast ? (finish.isPending ? "Scoring…" : "Finish quiz") : "Next"}
          </button>
        </div>
      )}

      {finish.isError && (
        <p className="status status--error" role="alert">
          {finish.error instanceof Error ? finish.error.message : "Could not submit the quiz"}
        </p>
      )}
    </section>
  );
}

/** Highlight the chosen and correct options once the answer is revealed. */
function optionClass(optionIndex: number, result: AnswerResult | null): string {
  if (!result) return "";
  if (optionIndex === result.correct_index) return "choice--correct";
  if (optionIndex === result.selected_index) return "choice--incorrect";
  return "";
}
