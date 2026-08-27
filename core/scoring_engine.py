"""Expert-calibrated logistic scoring and attribution."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.config_loader import TrackConfig


@dataclass
class ScoreOutput:
    logit: float
    probability: float
    raw_score: int
    active_count: int
    total_criteria: int
    used_fallback: bool = False
    positive_drivers: list[tuple[str, float]] = field(default_factory=list)
    risk_factors: list[tuple[str, float]] = field(default_factory=list)

    @property
    def odds_ratios(self) -> dict[str, float]:
        return {}


def _sigmoid(z: float) -> float:
    z_clipped = max(-15.0, min(15.0, z))
    return 1.0 / (1.0 + math.exp(-z_clipped))


def compute_candidate_score(
    features: dict[str, int | bool],
    config: TrackConfig,
) -> ScoreOutput:
    """Compute logit z, P(Pass), and attribution lists.

    Fallback: if total weight is 0 or no configured features resolve,
    use unweighted mean of binary flags as probability proxy.
    """
    questions = config.all_questions()
    weights = config.feature_weight_map()
    labels = config.label_map()
    total_criteria = len(questions)

    normalized: dict[str, int] = {}
    for qid in weights:
        raw = features.get(qid, 0)
        normalized[qid] = 1 if raw in (1, True, "1", "true", "True") else 0

    active_count = sum(normalized.values())
    raw_score = active_count
    total_weight = sum(weights.values())

    used_fallback = False
    if total_weight <= 0 or not normalized:
        used_fallback = True
        values = list(normalized.values()) or [0]
        probability = sum(values) / len(values)
        logit = math.log(probability / (1.0 - probability + 1e-12) + 1e-12)
    else:
        beta_0 = config.model_parameters.beta_0
        logit = beta_0 + sum(weights[qid] * normalized[qid] for qid in weights)
        probability = _sigmoid(logit)

    positive_drivers = sorted(
        [(labels[qid], weights[qid]) for qid, val in normalized.items() if val == 1],
        key=lambda item: item[1],
        reverse=True,
    )
    risk_factors = sorted(
        [(labels[qid], weights[qid]) for qid, val in normalized.items() if val == 0],
        key=lambda item: item[1],
        reverse=True,
    )

    return ScoreOutput(
        logit=logit,
        probability=probability,
        raw_score=raw_score,
        active_count=active_count,
        total_criteria=total_criteria,
        used_fallback=used_fallback,
        positive_drivers=positive_drivers,
        risk_factors=risk_factors,
    )


def odds_ratio(weight: float) -> float:
    return math.exp(weight)


def assign_statuses(
    probabilities: list[float],
    top_k: int,
    pass_threshold: float,
) -> list[str]:
    """Rank by probability desc. Top-K Pass (if >= threshold), next 2 Review, else Fail."""
    n = len(probabilities)
    order = sorted(range(n), key=lambda i: probabilities[i], reverse=True)
    statuses = ["Fail"] * n

    for rank, idx in enumerate(order):
        if rank < top_k and probabilities[idx] >= pass_threshold:
            statuses[idx] = "Top-K Pass"
        elif rank < top_k and probabilities[idx] < pass_threshold:
            statuses[idx] = "Review"
        elif rank < top_k + 2:
            statuses[idx] = "Review"
        else:
            statuses[idx] = "Fail"
    return statuses


def generate_attribution_notes(
    features: dict[str, int | bool],
    qualitative_notes: str,
    config: TrackConfig,
    score: ScoreOutput | None = None,
) -> str:
    score = score or compute_candidate_score(features, config)
    prefix = "[FALLBACK] " if score.used_fallback else ""
    logit_sign = f"{score.logit:+.2f}"
    score_pct = f"{score.probability * 100:.1f}%"

    if score.positive_drivers:
        drivers = ", ".join(f"{label} (+{weight:.2f})" for label, weight in score.positive_drivers)
    else:
        drivers = "None"

    if score.risk_factors:
        risks = ", ".join(f"{label} (+{weight:.2f})" for label, weight in score.risk_factors)
    else:
        risks = "None"

    notes = (qualitative_notes or "").strip() or "—"
    return (
        f"{prefix}[Score: {score_pct} | Logit: {logit_sign}] "
        f"Top Drivers: {drivers} | Risks: {risks} | Notes: {notes}"
    )


def sanitize_meeting_link(url: str | None) -> str:
    if not url or not str(url).strip():
        return "N/A"
    cleaned = "".join(ch for ch in str(url).strip() if ch.isprintable())
    cleaned = cleaned.replace(" ", "")
    if not cleaned:
        return "N/A"
    lower = cleaned.lower()
    if not (lower.startswith("http://") or lower.startswith("https://") or lower.startswith("meet.google")):
        if "." not in cleaned:
            return "N/A"
    return cleaned
