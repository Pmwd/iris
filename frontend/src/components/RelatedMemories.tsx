import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { FACT_REASON_LABELS, FACT_SCOPE_LABELS } from "../labels";
import type { FactRecall, RelatedMemoriesResponse, RoleId } from "../types";

export function RelatedMemories({
  query,
  role,
  projectId,
}: {
  query: string;
  role: RoleId;
  projectId: string | null;
}) {
  const [data, setData] = useState<RelatedMemoriesResponse | null>(null);

  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) {
      setData(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api
        .getRelatedMemories({
          q: text,
          role,
          project_id: projectId,
          limit: 4,
        })
        .then((result) => {
          if (!cancelled) setData(result);
        })
        .catch(() => {
          if (!cancelled) setData(null);
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, role, projectId]);

  if (!data || data.facts.length === 0) return null;

  return (
    <section className="memory-section related-memories">
      <div className="memory-section-head">
        <span>可能相关</span>
        <span className="pill">{data.facts.length}</span>
      </div>
      <ul className="fact-chip-list">
        {data.facts.map((fact: FactRecall) => (
          <li key={fact.id} className="fact-chip related-chip">
            <Link
              to={`/memory?q=${encodeURIComponent(fact.title)}`}
              className="fact-chip-title"
            >
              {fact.title}
            </Link>
            <span className="muted">
              {FACT_SCOPE_LABELS[fact.scope]} ·{" "}
              {FACT_REASON_LABELS[fact.reason] ?? fact.reason} ·{" "}
              {Math.round(fact.score * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
