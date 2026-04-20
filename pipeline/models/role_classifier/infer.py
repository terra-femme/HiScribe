import numpy as np
import os

WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), 'weights.keras')

_model = None


def _load():
    global _model
    import tensorflow as tf
    if os.path.exists(WEIGHTS_PATH):
        _model = tf.keras.models.load_model(WEIGHTS_PATH)
        print('[role_classifier] Weights loaded')
    else:
        from .model import build_model
        _model = build_model()
        print('[role_classifier] No weights found — using untrained model (run train.py first)')


def classify(
    pitch_mean: float,
    pitch_var: float,
    rate_wps: float,
    pause_ratio: float,
    avg_word_len: float,
    duration_s: float
) -> str:
    """
    Returns 'DOCTOR' or 'PATIENT'.
    Disagreements with pyannote diarization are flagged in the review UI.
    """
    global _model
    if _model is None:
        _load()

    features = np.array([[pitch_mean, pitch_var, rate_wps, pause_ratio, avg_word_len, duration_s]])
    prob = _model.predict(features, verbose=0)[0][0]
    return 'DOCTOR' if prob >= 0.5 else 'PATIENT'


def classify_batch(feature_rows: list) -> list:
    """
    Classify a list of segments in a single model call.

    Args:
        feature_rows: list of [pitch_mean, pitch_var, rate_wps,
                               pause_ratio, avg_word_len, duration_s]
    Returns:
        list of 'DOCTOR' or 'PATIENT', one per input row.
    """
    global _model
    if _model is None:
        _load()

    matrix = np.array(feature_rows, dtype=np.float32)   # shape (N, 6)
    probs = _model.predict(matrix, verbose=0)[:, 0]      # shape (N,)
    return ['DOCTOR' if p >= 0.5 else 'PATIENT' for p in probs]
