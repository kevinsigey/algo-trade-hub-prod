"""Kev seat (Kevin's succession call, Nov 11, 2026): the judge seat runs
on Kev -- jaredpalmer/kev-4b, an open decision model (LoRA + pointer head
on Qwen3.5-4B, Apache-2.0) served by SiliconFlow over OpenRouter's
/v1/systemone contract, the same wire shape as Jev. A live probe from the
production container (2026-11-12) answered HTTP 200 with the served build
jaredpalmer/kev-4b-20260924 at $0.042/M input tokens. Verdicts it renders
carry judge_id 'kev:jaredpalmer/kev-4b', a separate judge's record from
both 'jev:typesafe/jev-1.13' and 'free-ai-proposer', so the ~40-verdict
authority accounting never blends judges."""
import pytest

from tradehub.valuation import judge

PACKET = {
    "choices": [
        {"choice_id": "act_at_band_low", "label": "Act at the low band",
         "price": 272.18},
        {"choice_id": "act_at_band_mid", "label": "Act at the mid band",
         "price": 310.17},
        {"choice_id": "watch", "label": "Watch", "price": 460.42},
        {"choice_id": "pass", "label": "Pass", "price": 460.42},
    ],
    "rubric_weights": {"guide_credibility": 0.3, "gap_size": 0.25,
                       "direction_momentum": 0.15,
                       "options_expression": 0.1, "falsifier_proximity": 0.2},
    "digest": "AMGN trades 9.7 guide-range widths above its guide mid.",
    "proposer_pick": {"choice_id": "act_at_band_mid", "direction": "short",
                      "probability": 0.62},
    "rationale": "The price implies far more than the guide supports.",
}

# The shape the production probe actually returned (values from the
# probe's own toy packet; here they answer this module's packet).
PROBE_ANSWERS = {
    "model": "jaredpalmer/kev-4b-20260924",
    "answers": {
        "decision": {"type": "choice", "choice": "watch",
                     "probabilities": {"act_at_band_low": 0.1374,
                                       "act_at_band_mid": 0.0843,
                                       "watch": 0.4951, "pass": 0.2832},
                     "confidence": 0.3268},
        "direction": {"type": "choice", "choice": "none",
                      "probabilities": {"long": 0.0924, "short": 0.2315,
                                        "none": 0.6762},
                      "confidence": 0.5142}},
    "usage": {"input_tokens": 100, "output_tokens": 143},
}


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Post:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def _kev_seat(post):
    client = judge.SystemOneClient(judge.KEV_MODEL, "sk-test", post=post)
    return judge.KevSeat(client=client)


def test_kev_seat_renders_a_systemone_decision_and_names_itself():
    seat = _kev_seat(_Post(_Resp(200, PROBE_ANSWERS)))
    decision = seat.render(PACKET)
    assert seat.judge_id == "kev:jaredpalmer/kev-4b"
    assert decision["choice_id"] == "watch"
    assert decision["direction"] == "none"
    assert decision["probability"] == pytest.approx(0.4951)
    # A decision model generates no text: the rationale is empty and the
    # judge stamp carries the provenance, never invented prose.
    assert decision["rationale"] == ""


def test_kev_request_shape_is_the_systemone_contract():
    post = _Post(_Resp(200, PROBE_ANSWERS))
    _kev_seat(post).render(PACKET)
    url, kw = post.calls[0]
    assert url == "https://openrouter.ai/api/v1/systemone"
    assert kw["headers"]["Authorization"] == "Bearer sk-test"
    body = kw["json"]
    assert body["model"] == "jaredpalmer/kev-4b"
    assert set(body["questions"]) == {"decision", "direction"}
    criteria = body["questions"]["decision"]["criteria"]
    assert set(criteria) == {"act_at_band_low", "act_at_band_mid",
                             "watch", "pass"}
    assert "272.18" in criteria["act_at_band_low"]
    assert PACKET["digest"] in body["state"]


def test_kev_seat_selected_by_env_only_with_a_key():
    seat = judge.seat_for_env({"VALUATION_JUDGE": "kev",
                               "OPENROUTER_API_KEY": "sk-test"})
    assert isinstance(seat, judge.KevSeat)
    assert seat.judge_id == "kev:jaredpalmer/kev-4b"


def test_kev_seat_without_a_key_is_unavailable_not_silent():
    seat = judge.seat_for_env({"VALUATION_JUDGE": "kev"})
    with pytest.raises(judge.SeatUnavailable):
        seat.render(PACKET)


def test_kev_http_error_is_unavailable_with_the_status():
    seat = _kev_seat(_Post(_Resp(402, {"error": {"message": "no credits"}})))
    with pytest.raises(judge.SeatUnavailable) as exc:
        seat.render(PACKET)
    assert "402" in str(exc.value)


def test_kev_unknown_choice_answer_is_unavailable():
    bad = {"answers": {
        "decision": {"type": "choice", "choice": "bogus",
                     "probabilities": {"bogus": 1.0}, "confidence": 1.0},
        "direction": {"type": "choice", "choice": "none",
                      "probabilities": {"none": 1.0}, "confidence": 1.0}}}
    seat = _kev_seat(_Post(_Resp(200, bad)))
    with pytest.raises(judge.SeatUnavailable):
        seat.render(PACKET)


def _answers(decision_choice, direction_choice):
    return {"answers": {
        "decision": {"type": "choice", "choice": decision_choice,
                     "probabilities": {decision_choice: 0.6},
                     "confidence": 0.6},
        "direction": {"type": "choice", "choice": direction_choice,
                      "probabilities": {direction_choice: 0.7},
                      "confidence": 0.7}}}


def test_kev_watch_with_a_direction_is_forced_to_none():
    # Kev answers choice and direction as two independent questions, so
    # it can say "watch" and "short" in the same reply. A watch/pass
    # verdict carrying a direction would be stored as a directional
    # non-action; the seat forces direction none instead.
    seat = _kev_seat(_Post(_Resp(200, _answers("watch", "short"))))
    decision = seat.render(PACKET)
    assert decision["choice_id"] == "watch"
    assert decision["direction"] == "none"


def test_kev_pass_with_a_direction_is_forced_to_none():
    seat = _kev_seat(_Post(_Resp(200, _answers("pass", "long"))))
    decision = seat.render(PACKET)
    assert decision["choice_id"] == "pass"
    assert decision["direction"] == "none"


def test_kev_act_without_a_direction_abstains():
    # An act choice with direction none is a contradiction the other
    # way: acting needs a side. The seat abstains (SeatUnavailable)
    # rather than storing a directionless act.
    seat = _kev_seat(_Post(_Resp(200, _answers("act_at_band_low", "none"))))
    with pytest.raises(judge.SeatUnavailable):
        seat.render(PACKET)
    seat = _kev_seat(_Post(_Resp(200, _answers("act_at_band_mid", "none"))))
    with pytest.raises(judge.SeatUnavailable):
        seat.render(PACKET)


def test_kev_act_with_a_direction_passes_through():
    seat = _kev_seat(_Post(_Resp(200, _answers("act_at_band_mid", "short"))))
    decision = seat.render(PACKET)
    assert decision["choice_id"] == "act_at_band_mid"
    assert decision["direction"] == "short"


def test_kev_oversize_state_is_unavailable_and_never_sent():
    post = _Post(_Resp(200, PROBE_ANSWERS))
    seat = _kev_seat(post)
    big = dict(PACKET, digest="x" * 40000)  # ~10k tokens > the 8,192 cap
    with pytest.raises(judge.SeatUnavailable):
        seat.render(big)
    assert post.calls == []
