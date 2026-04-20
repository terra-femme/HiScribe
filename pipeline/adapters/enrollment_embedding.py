import io
import logging
import os

import numpy as np
import soundfile as sf
from cryptography.fernet import Fernet
from pyannote.audio import Inference, Model
from pyannote.audio.core.io import Audio
from pyannote.core import Segment

logger = logging.getLogger(__name__)

# --- Constants ---------------------------------------------------------------

MIN_DURATION_S = 15.0
MAX_DURATION_S = 20.0
WINDOW_DURATION_S = 3.0
WINDOW_STRIDE_S = 1.5
MIN_SEGMENT_S = 1.0          # segments shorter than this are skipped during matching
MATCH_THRESHOLD = 0.65       # cosine similarity required for a speaker → provider match

# --- Fernet key (loaded once at import) --------------------------------------

_FERNET_KEY = os.environ.get('VOICE_ENCRYPTION_KEY')
if not _FERNET_KEY:
    raise RuntimeError('[enrollment_embedding] VOICE_ENCRYPTION_KEY env var is not set')
_fernet = Fernet(_FERNET_KEY.encode() if isinstance(_FERNET_KEY, str) else _FERNET_KEY)

# --- Lazy embedding model singleton ------------------------------------------

_model: Model | None = None
_inference: Inference | None = None
_audio_io: Audio | None = None


def _load_embedding_model() -> None:
    global _model, _inference, _audio_io
    if _inference is not None:
        return
    hf_token = os.environ.get('HUGGINGFACE_TOKEN')
    logger.info('[enrollment_embedding] Loading pyannote/embedding model...')
    _model = Model.from_pretrained('pyannote/embedding', use_auth_token=hf_token)
    _inference = Inference(_model, window='whole')
    _audio_io = Audio(sample_rate=16000, mono=True)
    logger.info('[enrollment_embedding] Model ready')


# --- Embedding helpers -------------------------------------------------------

def _embed_segment(audio_path: str, start_s: float, end_s: float) -> np.ndarray:
    """Extract a single embedding for a time-bounded excerpt of an audio file."""
    _load_embedding_model()
    waveform, sr = _audio_io.crop(audio_path, Segment(start_s, end_s))
    embedding = _inference({'waveform': waveform, 'sample_rate': sr})
    return np.array(embedding).flatten()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 if either vector is zero-norm."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# --- Encryption helpers ------------------------------------------------------

def encrypt_embedding(embedding: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, embedding)
    return _fernet.encrypt(buf.getvalue())


def decrypt_embedding(encrypted: bytes) -> np.ndarray:
    raw = _fernet.decrypt(encrypted)
    return np.load(io.BytesIO(raw))


# --- Public API --------------------------------------------------------------

def build_enrollment_profile(audio_path: str) -> dict:
    """
    Build a voice enrollment profile from an audio file.

    Expects 15–20 seconds of clean speech. Uses a 3s sliding window with 1.5s
    stride to extract multiple embeddings, then averages them. Quality score is
    the mean pairwise cosine similarity between windows — higher means a more
    consistent, reliable voiceprint.

    Returns:
        {
            'embedding': np.ndarray,   # averaged embedding — caller must encrypt
            'quality_score': float,    # 0.0–1.0; reject below ~0.70
            'sample_count': int,       # number of windows used
        }

    Raises:
        ValueError: if audio is shorter than MIN_DURATION_S
    """
    _load_embedding_model()

    info = sf.info(audio_path)
    duration_s = info.duration
    logger.info('[enrollment_embedding] Audio duration: %.2fs path=%s', duration_s, audio_path)

    if duration_s < MIN_DURATION_S:
        raise ValueError(
            f'Enrollment audio too short: {duration_s:.1f}s (minimum {MIN_DURATION_S}s)'
        )

    clip_end = min(duration_s, MAX_DURATION_S)

    # Sliding window embeddings
    window_embeddings: list[np.ndarray] = []
    start = 0.0
    while start + WINDOW_DURATION_S <= clip_end:
        end = start + WINDOW_DURATION_S
        emb = _embed_segment(audio_path, start, end)
        window_embeddings.append(emb)
        logger.debug('[enrollment_embedding] Window %.1f–%.1f extracted shape=%s', start, end, emb.shape)
        start += WINDOW_STRIDE_S

    sample_count = len(window_embeddings)
    logger.info('[enrollment_embedding] Extracted %d window embeddings', sample_count)

    averaged = np.mean(window_embeddings, axis=0)

    # Quality score: mean pairwise cosine similarity between window embeddings
    if sample_count < 2:
        quality_score = 1.0  # only one window — no comparison possible
    else:
        sims = []
        for i in range(sample_count):
            for j in range(i + 1, sample_count):
                sims.append(cosine_similarity(window_embeddings[i], window_embeddings[j]))
        quality_score = float(np.mean(sims))

    logger.info('[enrollment_embedding] Enrollment quality_score=%.3f samples=%d', quality_score, sample_count)

    return {
        'embedding': averaged,
        'quality_score': quality_score,
        'sample_count': sample_count,
    }


def match_speakers(
    audio_path: str,
    diarization_windows: list[dict],
    enrolled_providers: list[dict],
) -> dict:
    """
    Match diarized speaker labels to enrolled providers.

    For each unique speaker label, collects all diarization segments ≥ MIN_SEGMENT_S,
    extracts an embedding per segment, averages them, then compares against each
    enrolled provider using cosine similarity.

    Args:
        audio_path: path to the session WAV file
        diarization_windows: list of {start_ms, end_ms, speaker_label}
        enrolled_providers: list of DB records from get_active_enrollments()
                            each must have: provider_id, name, encrypted_embedding

    Returns:
        { speaker_label: { 'provider_id': str, 'name': str, 'confidence': float } }
        Only matched speakers (≥ MATCH_THRESHOLD) are included.
        Unmatched speakers are absent — caller decides their fallback label.
    """
    if not enrolled_providers:
        logger.info('[enrollment_embedding] No enrolled providers — skipping speaker matching')
        return {}

    _load_embedding_model()

    # Decrypt enrolled embeddings once
    provider_profiles: list[dict] = []
    for p in enrolled_providers:
        try:
            emb = decrypt_embedding(p['encrypted_embedding'])
            provider_profiles.append({
                'provider_id': p['provider_id'],
                'name': p['name'],
                'embedding': emb,
            })
        except Exception:
            logger.warning('[enrollment_embedding] Failed to decrypt embedding for provider_id=%s — skipping',
                           p['provider_id'])

    if not provider_profiles:
        logger.warning('[enrollment_embedding] All provider embeddings failed decryption')
        return {}

    # Group diarization windows by speaker label
    speaker_segments: dict[str, list[dict]] = {}
    for w in diarization_windows:
        label = w['speaker_label']
        speaker_segments.setdefault(label, []).append(w)

    result: dict = {}

    for label, segments in speaker_segments.items():
        seg_embeddings: list[np.ndarray] = []

        for seg in segments:
            start_s = seg['start_ms'] / 1000.0
            end_s = seg['end_ms'] / 1000.0
            duration = end_s - start_s

            if duration < MIN_SEGMENT_S:
                logger.debug('[enrollment_embedding] Skipping short segment %.2fs for %s', duration, label)
                continue

            try:
                emb = _embed_segment(audio_path, start_s, end_s)
                seg_embeddings.append(emb)
            except Exception as exc:
                logger.warning('[enrollment_embedding] Embedding failed for segment %s %.1f–%.1f: %s',
                               label, start_s, end_s, exc)

        if not seg_embeddings:
            logger.warning('[enrollment_embedding] No usable segments for speaker %s', label)
            continue

        speaker_emb = np.mean(seg_embeddings, axis=0)
        logger.debug('[enrollment_embedding] Speaker %s: averaged %d segment embedding(s)', label, len(seg_embeddings))

        # Compare against each enrolled provider
        best_provider_id = None
        best_name = None
        best_confidence = 0.0

        for profile in provider_profiles:
            sim = cosine_similarity(speaker_emb, profile['embedding'])
            logger.debug('[enrollment_embedding] %s vs %s similarity=%.3f', label, profile['provider_id'], sim)
            if sim > best_confidence:
                best_confidence = sim
                best_provider_id = profile['provider_id']
                best_name = profile['name']

        if best_confidence >= MATCH_THRESHOLD:
            result[label] = {
                'provider_id': best_provider_id,
                'name': best_name,
                'confidence': round(best_confidence, 4),
            }
            logger.info('[enrollment_embedding] Matched %s → %s (%.3f)', label, best_name, best_confidence)
        else:
            logger.info('[enrollment_embedding] No match for %s (best=%.3f below threshold %.2f)',
                        label, best_confidence, MATCH_THRESHOLD)

    return result
