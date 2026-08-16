import { useState } from "react";

import type { QuizResult } from "../services/api";

interface Props {
  result: QuizResult;
  onRestart: () => void;
}

/** Final score, with the option to review what was answered incorrectly. */
export function QuizReview({ result, onRestart }: Props) {
  const [showReview, setShowReview] = useState(false);
  const wrong = result.questions.filter((question) => question.is_correct === false);

  return (
    <section className="card">
      <h2>Quiz results</h2>

      <p className="score">
        Score: {result.score} / {result.total}
      </p>

      <ul className="tally">
        <li className="status--ok">Correct: {result.correct}</li>
        <li className="status--error">Incorrect: {result.incorrect}</li>
        {result.unanswered > 0 && <li>Unanswered: {result.unanswered}</li>}
      </ul>

      <div className="row">
        {wrong.length > 0 && (
          <button type="button" onClick={() => setShowReview((current) => !current)}>
            {showReview ? "Hide review" : `Review ${wrong.length} incorrect`}
          </button>
        )}
        <button type="button" onClick={onRestart}>
          New quiz
        </button>
      </div>

      {showReview &&
        wrong.map((question) => (
          <article key={question.id} className="review">
            <p className="question">{question.question}</p>
            <p className="status status--error">
              Your answer:{" "}
              {question.selected_index === null
                ? "not answered"
                : question.options[question.selected_index]}
            </p>
            <p className="status status--ok">
              Correct answer: {question.options[question.correct_index]}
            </p>
            <p className="explanation">{question.explanation}</p>
            <p className="field__hint">Source: {question.source}</p>
          </article>
        ))}
    </section>
  );
}
