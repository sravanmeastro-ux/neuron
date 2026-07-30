"""Web search + local LLM summarize (free; uses DDG/Google scrape + Ollama)."""

from __future__ import annotations


def web_search_summarize(args: dict) -> str:
    query = (args.get("query") or args.get("q") or "").strip()
    if not query:
        return "Need a search query."
    evidence = []
    try:
        import howto_learn
        hits = howto_learn.search_google(query, limit=5)
        for h in hits:
            evidence.append(f"- {h.get('title')}: {h.get('snippet')} ({h.get('url')})")
    except Exception as exc:
        evidence.append(f"(search error: {exc})")

    blob = "\n".join(evidence)[:4000]
    if len(blob) < 20:
        return f"Couldn't search for: {query}"

    try:
        import brain_llm
        if brain_llm.is_enabled():
            raw = brain_llm.chat_json(
                [
                    {
                        "role": "system",
                        "content": 'Summarize web results for the user. JSON: {"say":"<summary under 80 words>","steps":[]}',
                    },
                    {"role": "user", "content": f"Query: {query}\nResults:\n{blob}"},
                ],
                timeout=30,
            )
            import json, re
            try:
                data = json.loads(raw)
            except Exception:
                m = re.search(r"\{.*\}", raw or "", re.S)
                data = json.loads(m.group(0)) if m else {"say": raw}
            return (data.get("say") or raw or "")[:600]
    except Exception:
        pass
    return f"Results for {query}:\n" + "\n".join(evidence[:4])
