import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "../services/api";

/** Shows whether the frontend can reach the backend API. */
export function BackendStatus() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });

  if (isPending) {
    return <p className="status">Checking backend…</p>;
  }

  if (isError) {
    return <p className="status status--error">Backend unavailable</p>;
  }

  return (
    <p className="status status--ok">
      Backend ready — {data.app} v{data.version} ({data.environment})
    </p>
  );
}
