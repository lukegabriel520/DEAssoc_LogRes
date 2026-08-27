"""Package init."""

from core.config_loader import TrackConfig, load_department_rubric, parse_config
from core.scoring_engine import compute_candidate_score, generate_attribution_notes

__all__ = [
    "TrackConfig",
    "load_department_rubric",
    "parse_config",
    "compute_candidate_score",
    "generate_attribution_notes",
]
