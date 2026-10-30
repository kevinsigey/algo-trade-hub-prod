"""Ideas and their runs in Supabase. Insert and read only: nothing here updates or deletes a run."""

from __future__ import annotations

IDEAS, RUNS = "ideas", "idea_runs"


def create_idea(supa, title: str, plain_words: str) -> dict:
    return supa.table(IDEAS).insert({"title": title, "plain_words": plain_words}).execute().data[0]


def get_idea(supa, idea_id: int) -> dict | None:
    rows = supa.table(IDEAS).select("*").eq("id", idea_id).execute().data
    if not rows:
        return None
    runs = supa.table(RUNS).select("*").eq("idea_id", idea_id).order("variation").execute().data
    return {"idea": rows[0], "runs": runs}


def list_ideas(supa) -> list[dict]:
    ideas = supa.table(IDEAS).select("*").order("created_at", desc=True).execute().data
    runs = supa.table(RUNS).select("idea_id,variation,verdict").execute().data
    latest: dict[int, tuple[int, str]] = {}
    for r in runs:
        if r["variation"] > latest.get(r["idea_id"], (0, ""))[0]:
            latest[r["idea_id"]] = (r["variation"], r["verdict"])
    return [{"id": i["id"], "title": i["title"], "created_at": i["created_at"],
             "runs": latest.get(i["id"], (0, None))[0], "latest_verdict": latest.get(i["id"], (0, None))[1]}
            for i in ideas]


def insert_run(supa, idea_id: int, variation: int, spec: dict, draft_model: str | None, result: dict) -> dict:
    row = {"idea_id": idea_id, "variation": variation, "spec": spec, "draft_model": draft_model,
           "verdict": result["verdict"], "result": result, "data_end": result.get("data_end")}
    return supa.table(RUNS).insert(row).execute().data[0]
