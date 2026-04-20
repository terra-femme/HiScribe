import logging

import librosa
import numpy as np

logger = logging.getLogger(__name__)

# RMS energy floor below which a frame is considered silence.
# 0.01 ≈ -40 dBFS — captures breath pauses and inter-word gaps
# without flagging soft speech as silence.
_SILENCE_FLOOR = 0.01


def extract_acoustic_features(
    audio_path: str, start_ms: int, end_ms: int
) -> tuple[float, float, float]:
    """
    Extract (pitch_mean, pitch_var, pause_ratio) for a single segment slice.

    Pitch is extracted via librosa.piptrack() — the dominant pitch per frame
    is taken as the bin with highest magnitude, zero-pitch frames are excluded.

    pause_ratio is the fraction of RMS frames below _SILENCE_FLOOR (0.01).
    This is an absolute energy floor, not a percentile, so it varies with
    actual silence content rather than being constant across all segments.

    Returns stub fallback (150.0, 20.0, 0.2) on any error so that
    role_classify_node degrades gracefully when audio is unavailable.

    Adapted from MedJournee/services/voice_enrollment_service.py:_extract_voice_features()
    """
    try:
        start_s  = start_ms / 1000.0
        end_s    = end_ms   / 1000.0
        duration = end_s - start_s

        if duration < 0.1:
            return 150.0, 20.0, 0.2

        # Load only the segment slice — avoids holding the full session WAV in memory
        audio, sr = librosa.load(
            audio_path, sr=16000, mono=True,
            offset=start_s, duration=duration
        )

        if len(audio) == 0:
            return 150.0, 20.0, 0.2

        # ── Pitch via piptrack ────────────────────────────────────────────────
        pitches, magnitudes = librosa.piptrack(y=audio, sr=sr, threshold=0.1)
        pitch_values = []
        for t in range(pitches.shape[1]):
            idx   = magnitudes[:, t].argmax()
            pitch = pitches[idx, t]
            if pitch > 0:
                pitch_values.append(pitch)

        if pitch_values:
            pitch_mean = float(np.mean(pitch_values))
            pitch_var  = float(np.std(pitch_values))
        else:
            pitch_mean, pitch_var = 150.0, 20.0

        # ── Pause ratio: fraction of frames below absolute silence floor ──────
        # Using np.percentile(energy, 20) would always return ~0.20 by definition
        # regardless of actual silence content — fixed to an absolute threshold.
        energy      = librosa.feature.rms(y=audio)[0]
        pause_ratio = float(np.mean(energy < _SILENCE_FLOOR))

        logger.debug(
            '[acoustic] %dms–%dms pitch_mean=%.1f pitch_var=%.1f pause_ratio=%.3f',
            start_ms, end_ms, pitch_mean, pitch_var, pause_ratio
        )
        return pitch_mean, pitch_var, pause_ratio

    except Exception as exc:
        logger.debug('[acoustic] Feature extraction failed (%s) — using stubs', exc)
        return 150.0, 20.0, 0.2
