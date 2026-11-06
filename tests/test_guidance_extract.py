"""Guidance extraction (Kevin, 2026-11-06): the model reads a release, and a number is kept only if an exact quote
from the release backs it. Network and model are faked."""
from tradehub.guidance import extract as gx

RELEASE = """<html><body><p>ACME Reports Third Quarter Results</p>
<p>For the fourth quarter of fiscal 2026, ACME expects revenue of $9.6 billion to $10.0 billion
and non-GAAP earnings per share of $1.20 to $1.26.</p>
<p>The company now expects full-year capital expenditures of approximately $42 billion.</p>
<script>var x = "$999 billion";</script></body></html>"""


def test_html_becomes_plain_text_without_scripts():
    text = gx.html_to_text(RELEASE)
    assert "expects revenue of $9.6 billion to $10.0 billion" in text
    assert "$999" not in text and "<p>" not in text


def _item(**over):
    base = {"period": "Q4 FY2026", "metric": "revenue", "unit": "usd", "scale": "billions", "low": 9.6, "high": 10.0,
            "evidence": "ACME expects revenue of $9.6 billion to $10.0 billion"}
    base.update(over)
    return gx.GuidanceItem(**base)


def test_an_item_is_kept_only_when_its_quote_and_numbers_are_in_the_release():
    text = gx.html_to_text(RELEASE)
    good = _item()
    eps = _item(metric="eps_adjusted", unit="usd_per_share", scale="units", low=1.20, high=1.26,
                evidence="non-GAAP earnings per share of $1.20 to $1.26")
    capex = _item(period="FY2026", metric="capex", low=42, high=42,
                  evidence="expects full-year capital expenditures of approximately $42 billion")
    invented_number = _item(low=9.5)                                    # 9.5 is not in the quote
    invented_quote = _item(evidence="ACME expects revenue of $11 billion", low=11, high=11)  # not in the release
    kept, dropped = gx.verify([good, eps, capex, invented_number, invented_quote], text)
    assert kept == [good, eps, capex] and dropped == 2


def test_quote_matching_ignores_whitespace_and_curly_quotes():
    text = gx.html_to_text("<p>revenue  of\n$9.6 billion to $10.0 billion</p>")
    kept, _ = gx.verify([_item(evidence="revenue of $9.6 billion to $10.0 billion")], text)
    assert len(kept) == 1


def test_values_are_stored_in_base_units():
    assert gx.to_base(9.6, "billions") == 9.6e9 and gx.to_base(1.2, "units") == 1.2 and gx.to_base(None, "billions") is None


def test_the_model_reply_is_read_from_a_free_openrouter_route():
    """Kevin, 2026-11-06: free models only (OpenRouter's free route, as the agent debates use), no paid Claude calls.
    Reasoning models may wrap the JSON in prose; the outermost object is read."""
    import json as _json

    def post(url, headers=None, json=None, timeout=None):
        assert url == gx.OPENROUTER_URL and headers["Authorization"] == "Bearer k"
        assert json["models"] and all(m.endswith(":free") for m in json["models"]) and len(json["models"]) <= 3
        assert json["response_format"]["type"] == "json_schema"

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                body = _json.dumps({"no_guidance": False, "items": [_item().model_dump()]})
                return {"model": "some/free-model:free", "choices": [{"finish_reason": "stop",
                        "message": {"content": "Here is the guidance: " + body + " done."}}]}
        return R()

    env = gx.ask_model("some release text", key="k", post=post)
    assert env.items == [_item()] and env.model == "some/free-model:free"


def test_a_run_extracts_new_filings_and_marks_them(monkeypatch):
    from workshop_fake import DB

    db = DB()
    db.table("guidance_filings").insert([
        {"accession": "a1", "ticker": "ACME", "cik": "0000000001", "doc_url": "u1", "status": "new"},
        {"accession": "a2", "ticker": "BETA", "cik": "0000000002", "doc_url": "u2", "status": "new"},
    ]).execute()

    def model(text, **_k):
        if "BETA" in text:
            return gx.Envelope(no_guidance=True, items=[], model="m")
        return gx.Envelope(no_guidance=False, model="m", items=[
            _item(), _item(low=9.5, evidence="ACME expects revenue of $9.6 billion to $10.0 billion")])

    out = gx.run(db, fetch=lambda url: RELEASE if url == "u1" else "<p>BETA reports results.</p>", model=model,
                 consensus=lambda ticker, metric, period: (10.1e9, "0q", "yfinance"), key="k")
    assert out == {"extracted": 1, "no_guidance": 1, "failed": 0, "records": 1, "dropped": 1}
    filings = {r["accession"]: r for r in db.db["guidance_filings"]}
    assert filings["a1"]["status"] == "extracted" and filings["a1"]["dropped"] == 1
    assert filings["a2"]["status"] == "no_guidance"
    [rec] = db.db["guidance_records"]
    assert rec["low"] == 9.6e9 and rec["high"] == 10.0e9 and rec["consensus"] == 10.1e9 and rec["model"] == "m"


def test_without_a_key_nothing_is_marked_and_the_run_says_so():
    from workshop_fake import DB

    db = DB()
    db.table("guidance_filings").insert([{"accession": "a1", "ticker": "ACME", "doc_url": "u1", "status": "new"}]).execute()
    out = gx.run(db, fetch=lambda url: RELEASE, model=None, consensus=None, key="")
    assert out == {"skipped": "no model key", "waiting": 1}
    assert db.db["guidance_filings"][0]["status"] == "new"


def test_per_share_and_percent_values_are_never_scaled():
    # A free model labelled AbbVie's $13.95-$13.99 EPS guide "billions" (2026-11-06): per-share values stay as written.
    assert gx.stored_values(_item(metric="eps_adjusted", unit="usd_per_share", scale="billions", low=13.95, high=13.99)) == (13.95, 13.99)
    assert gx.stored_values(_item(metric="operating_margin", unit="pct", scale="millions", low=30, high=32)) == (30, 32)
    assert gx.stored_values(_item()) == (9.6e9, 10.0e9)


def test_the_quote_must_name_the_metric_and_never_be_a_dividend():
    text = gx.html_to_text(RELEASE + "<p>The board declared a quarterly dividend of $1.82 per share.</p>")
    dividend_as_capex = _item(metric="capex", low=1.82, high=1.82, evidence="declared a quarterly dividend of $1.82 per share")
    eps_named_revenue = _item(metric="eps_adjusted", unit="usd_per_share", scale="units", low=1.20, high=1.26,
                              evidence="non-GAAP earnings per share of $1.20 to $1.26")
    revenue_quote_as_capex = _item(metric="capex")  # the quote talks about revenue
    kept, dropped = gx.verify([dividend_as_capex, eps_named_revenue, revenue_quote_as_capex], text)
    assert kept == [eps_named_revenue] and dropped == 2
