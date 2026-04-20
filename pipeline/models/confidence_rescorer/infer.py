import torch
import os
from .model import ConfidenceRescorer

SECTION_IDX = {'S': 0, 'O': 1, 'A': 2, 'P': 3}
WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), 'weights.pt')

_model = None


def _load():
    global _model
    _model = ConfidenceRescorer()
    if os.path.exists(WEIGHTS_PATH):
        _model.load_state_dict(torch.load(WEIGHTS_PATH, map_location='cpu', weights_only=True))
        print('[confidence_rescorer] Weights loaded')
    else:
        print('[confidence_rescorer] No weights found — using untrained model (run train.py after collecting data)')
    _model.eval()


def score(asr_confidence: float, token_count: int, soap_section: str) -> float:
    """
    Returns a reliability score [0, 1].
    Segments below 0.6 are flagged in the review UI.
    """
    global _model
    if _model is None:
        _load()

    onehot = [0.0] * 4
    onehot[SECTION_IDX.get(soap_section or 'S', 0)] = 1.0
    x = torch.tensor([[asr_confidence, float(token_count)] + onehot], dtype=torch.float32)

    with torch.no_grad():
        return _model(x).item()
