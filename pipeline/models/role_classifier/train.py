"""
Training script for the role classifier (DOCTOR vs PATIENT).

Training data: segments from approved sessions where provider corrected the role label.
  - segment_remapped audit events where the corrected speaker = DOCTOR → label 1
  - segment_remapped audit events where the corrected speaker = PATIENT → label 0

For initial training without real data, use synthetic data from LibriSpeech:
  - Annotate ~200 clips as doctor-like (fast, technical)
  - Annotate ~200 clips as patient-like (slow, descriptive)
  - Extract features with librosa
  - Feed to this script

Run: python -m models.role_classifier.train
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from adapters.acoustic_features import extract_acoustic_features
from db.sqlite import _conn
from models.role_classifier.model import build_model

WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), 'weights.keras')


def load_training_data():
    """
    Loads labeled samples from segments + provider_enrollments.
    Falls back to synthetic data if no real labeled data is available yet.

    Label logic (correct):
    - Segments where speaker matches an enrolled provider name → DOCTOR (1)
    - Segments where speaker does not match any enrollment → PATIENT (0)
    - Segments with SPEAKER_XX / SPEAKER_UNKNOWN labels are excluded —
      those were never resolved by enrollment so their role is unknown.

    This is the only ground-truth source that is semantically correct.
    SOAP section remap events (previous approach) indicate content category,
    not speaker role — a doctor summarising patient history lands in S but
    the speaker is still DOCTOR.

    Acoustic features use the same extract_acoustic_features() as inference
    so train/inference feature distributions are always aligned.
    """
    audio_base = os.path.join(os.path.dirname(__file__), '../../../data/audio')
    samples    = []

    with _conn() as conn:
        rows = conn.execute("""
            SELECT
                s.start_ms,
                s.end_ms,
                s.text,
                s.session_id,
                CASE WHEN pe.provider_id IS NOT NULL THEN 1 ELSE 0 END AS label
            FROM segments s
            LEFT JOIN provider_enrollments pe ON s.speaker = pe.name
            WHERE s.is_final = 1
              AND s.speaker IS NOT NULL
              AND s.speaker != ''
              AND s.speaker NOT LIKE 'SPEAKER_%'
        """).fetchall()

    for row in rows:
        start_ms   = row['start_ms']
        end_ms     = row['end_ms']
        text       = row['text'] or ''
        session_id = row['session_id']
        label      = int(row['label'])

        audio_path = os.path.join(audio_base, f'{session_id}.wav')
        pitch_mean, pitch_var, pause_ratio = extract_acoustic_features(
            audio_path, start_ms, end_ms
        )

        words        = text.split()
        duration_s   = (end_ms - start_ms) / 1000
        rate_wps     = len(words) / max(duration_s, 0.1)
        avg_word_len = sum(len(w) for w in words) / max(len(words), 1)

        samples.append(([pitch_mean, pitch_var, rate_wps, pause_ratio, avg_word_len, duration_s], label))

    print(f'[train] Loaded {len(samples)} real labeled samples '
          f'({sum(1 for s in samples if s[1] == 1)} DOCTOR, '
          f'{sum(1 for s in samples if s[1] == 0)} PATIENT)')

    if not samples:
        print('[train] No real data yet — generating synthetic training set')
        np.random.seed(42)
        # DOCTOR: higher rate, longer words, lower pause ratio
        doctor_features = np.random.normal(
            loc=[140, 15, 3.2, 0.1, 6.5, 8.0],
            scale=[20, 5, 0.5, 0.05, 1.0, 2.0],
            size=(200, 6)
        )
        # PATIENT: lower rate, shorter words, higher pause ratio
        patient_features = np.random.normal(
            loc=[180, 30, 1.8, 0.3, 4.5, 5.0],
            scale=[25, 8, 0.4, 0.1, 0.8, 1.5],
            size=(200, 6)
        )
        X = np.vstack([doctor_features, patient_features])
        y = np.array([1] * 200 + [0] * 200, dtype=np.float32)
        return X, y

    X = np.array([s[0] for s in samples])
    y = np.array([s[1] for s in samples], dtype=np.float32)
    return X, y


def train(epochs: int = 30):
    X, y = load_training_data()
    model = build_model()

    model.fit(
        X, y,
        epochs=epochs,
        batch_size=32,
        validation_split=0.2,
        verbose=1
    )

    model.save(WEIGHTS_PATH)
    print(f'[train] Weights saved to {WEIGHTS_PATH}')


if __name__ == '__main__':
    train()
