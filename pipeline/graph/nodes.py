"""
pipeline/graph/nodes.py

Changes applied:
  - Audio deletion in package_node — WAV file removed after pipeline completes (HIPAA)
  - Speaker confidence guard in diarize_node — segments with no matching
    diarization window (positional fallback) are marked SPEAKER_UNKNOWN
    and given diarization_confidence=0.0; displayed in review payload
  - Aggressive debug logging at every step so failures are immediately locatable
"""

from typing import TypedDict, List
import os
import logging

from db.sqlite import (
    get_segments, update_segment_diarization,
    update_segment_mapping, update_segment_score
)
from db.enrollment import get_active_enrollments
from adapters.acoustic_features import extract_acoustic_features
from adapters.diarize import diarize
from adapters.enrollment_embedding import match_speakers
from adapters.llm import map_segments
from models.confidence_rescorer.infer import score as rescore
from models.role_classifier.infer import classify_batch as role_classify_batch

logger = logging.getLogger('hiscribe.pipeline')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(name)s] %(levelname)s %(message)s'
)

AUDIO_DIR = os.path.join(os.path.dirname(__file__), '../../data/audio')

# Speaker confidence threshold — segments below this are set to SPEAKER_UNKNOWN
# rather than trusted. 0.0 means "no diarization window matched at all."
SPEAKER_CONFIDENCE_THRESHOLD = 0.0  # flag only unmatched segments for now


class ScribeState(TypedDict):
    session_id: str
    segments: List[dict]
    role_flags: List[str]               # segment_ids where diarization + classifier disagree
    speaker_unknown_ids: List[str]      # segment_ids where no diarization window matched
    speaker_map: dict                   # {speaker_label: {provider_id, name, confidence}} from enrollment
    mapped_segments: List[dict]         # adds: soap_section per segment
    scored_segments: List[dict]         # adds: reliability_score, flags
    review_payload: dict


# ─── Node 1: Load all final segments ─────────────────────────────────────────

def finalize_node(state: ScribeState) -> ScribeState:
    session_id = state['session_id']
    logger.info(f'[finalize] Loading segments for session {session_id}')
    segments = get_segments(session_id)
    logger.info(f'[finalize] {len(segments)} segments loaded')

    if not segments:
        logger.warning(f'[finalize] No segments found for session {session_id} — pipeline will produce empty output')

    return {**state, 'segments': segments, 'speaker_unknown_ids': []}


# ─── Node 2: pyannote diarization + speaker confidence guard ─────────────────

def diarize_node(state: ScribeState) -> ScribeState:
    session_id = state['session_id']
    audio_path = os.path.join(AUDIO_DIR, f'{session_id}.wav')

    if not os.path.exists(audio_path):
        logger.warning(f'[diarize] No audio file at {audio_path} — skipping diarization')
        return state

    logger.info(f'[diarize] Running pyannote on {audio_path}')

    try:
        diarization = diarize(audio_path)
    except Exception as e:
        logger.error(f'[diarize] Diarization failed: {e}', exc_info=True)
        return state

    logger.info(f'[diarize] Got {len(diarization)} speaker windows from pyannote')
    for w in diarization:
        logger.debug(
            f'[diarize] Window: {w["speaker_label"]} '
            f'{w["start_ms"]}ms – {w["end_ms"]}ms '
            f'(duration={w["end_ms"] - w["start_ms"]}ms)'
        )

    segments = state['segments']
    speaker_unknown_ids = []
    matched = 0
    unmatched = 0

    for seg in segments:
        label, confidence = _match_speaker_with_confidence(
            seg['start_ms'], seg['end_ms'], diarization
        )
        seg['speaker'] = label
        seg['diarization_confidence'] = confidence

        if confidence <= SPEAKER_CONFIDENCE_THRESHOLD:
            # No diarization window matched this segment's midpoint
            seg['speaker'] = 'SPEAKER_UNKNOWN'
            seg['speaker_confidence_flag'] = True
            speaker_unknown_ids.append(seg['segment_id'])
            unmatched += 1
            logger.warning(
                f'[diarize] Segment {seg["segment_id"]} has no matching diarization window '
                f'(mid={(_mid(seg["start_ms"], seg["end_ms"])):.0f}ms) — '
                f'set to SPEAKER_UNKNOWN'
            )
        else:
            seg['speaker_confidence_flag'] = False
            matched += 1
            logger.debug(
                f'[diarize] Segment {seg["segment_id"]} → {label} '
                f'(conf={confidence:.2f})'
            )

        update_segment_diarization(seg['segment_id'], seg['speaker'], role_flag=False)

    logger.info(
        f'[diarize] Diarization complete — matched={matched} unmatched={unmatched} '
        f'(SPEAKER_UNKNOWN assigned to {len(speaker_unknown_ids)} segments)'
    )

    return {**state, 'segments': segments, 'speaker_unknown_ids': speaker_unknown_ids}


def _mid(start_ms: int, end_ms: int) -> float:
    return (start_ms + end_ms) / 2.0


def _match_speaker_with_confidence(
    start_ms: int, end_ms: int, diarization: list
) -> tuple[str, float]:
    """
    Returns (speaker_label, confidence).

    Confidence is currently binary:
      1.0  — segment midpoint falls within a diarization window
      0.0  — no window matched (positional fallback was used previously)

    Future improvement: compute confidence as how centred the midpoint is
    within the matched window — segments near boundaries are less reliable.
    """
    mid = _mid(start_ms, end_ms)
    for window in diarization:
        if window['start_ms'] <= mid <= window['end_ms']:
            return window['speaker_label'], 1.0
    return 'SPEAKER_UNKNOWN', 0.0


# ─── Node 3: Resolve diarized speaker labels to enrolled provider names ───────

def resolve_speakers_node(state: ScribeState) -> ScribeState:
    """
    Maps SPEAKER_00/SPEAKER_01 labels to enrolled provider names using
    pyannote embedding cosine similarity.

    Fallback behaviour (safe for existing sessions):
    - No audio file present → returns state unchanged, speaker_map = {}
    - No enrolled providers → returns state unchanged, speaker_map = {}
    - Match below threshold → speaker label left as SPEAKER_XX, no speaker_role set
    - Unmatched speaker when at least one other speaker matched → labeled PATIENT

    After this node, seg['speaker'] may be a provider name (e.g. "Dr. Smith")
    and seg['speaker_role'] may be 'DOCTOR' or 'PATIENT'. role_classify_node
    uses speaker_role when present instead of the SPEAKER_XX string heuristic.
    """
    session_id = state['session_id']
    audio_path = os.path.join(AUDIO_DIR, f'{session_id}.wav')

    if not os.path.exists(audio_path):
        logger.info('[resolve] No audio file at %s — skipping speaker resolution', audio_path)
        return {**state, 'speaker_map': {}}

    enrolled = get_active_enrollments()
    if not enrolled:
        logger.info('[resolve] No enrolled providers — SPEAKER_XX labels unchanged')
        return {**state, 'speaker_map': {}}

    segments = state['segments']

    # Build diarization windows from segments — each segment already carries
    # speaker and time bounds from diarize_node
    windows = [
        {'start_ms': seg['start_ms'], 'end_ms': seg['end_ms'], 'speaker_label': seg['speaker']}
        for seg in segments
        if seg.get('speaker') not in ('SPEAKER_UNKNOWN', None)
    ]

    if not windows:
        logger.info('[resolve] No usable windows for speaker matching')
        return {**state, 'speaker_map': {}}

    try:
        speaker_map = match_speakers(audio_path, windows, enrolled)
    except Exception as exc:
        logger.error('[resolve] Speaker matching failed: %s', exc, exc_info=True)
        return {**state, 'speaker_map': {}}

    if not speaker_map:
        logger.info('[resolve] No speakers matched enrolled providers — labels unchanged')
        return {**state, 'speaker_map': {}}

    # Any speaker label not matched → treat as PATIENT (by elimination)
    all_labels = {w['speaker_label'] for w in windows}
    unmatched_labels = all_labels - set(speaker_map.keys())

    for seg in segments:
        label = seg.get('speaker')
        if label in speaker_map:
            match = speaker_map[label]
            seg['speaker']      = match['name']
            seg['speaker_role'] = 'DOCTOR'
            update_segment_diarization(seg['segment_id'], match['name'], role_flag=False)
            logger.debug('[resolve] Segment %s → %s (conf=%.3f)',
                         seg['segment_id'], match['name'], match['confidence'])
        elif label in unmatched_labels:
            seg['speaker_role'] = 'PATIENT'
            logger.debug('[resolve] Segment %s → PATIENT (unmatched label %s)',
                         seg['segment_id'], label)

    matched_names = [v['name'] for v in speaker_map.values()]
    logger.info('[resolve] Resolved %d speaker(s): %s | unmatched: %s',
                len(speaker_map), matched_names, list(unmatched_labels))

    return {**state, 'segments': segments, 'speaker_map': speaker_map}


# ─── Node 4: Role classifier cross-check ─────────────────────────────────────

def role_classify_node(state: ScribeState) -> ScribeState:
    segments   = state['segments']
    role_flags = []
    audio_path = os.path.join(AUDIO_DIR, f'{state["session_id"]}.wav')
    has_audio  = os.path.exists(audio_path)

    if not has_audio:
        logger.info('[role_classify] No audio file — acoustic features will use stubs')

    logger.info(f'[role_classify] Checking {len(segments)} segments')

    # Build feature matrix for all classifiable segments in one pass
    # (skips unknown-speaker segments — no reliable acoustic anchor)
    to_classify = []
    for seg in segments:
        if seg.get('speaker_confidence_flag'):
            logger.debug(
                f'[role_classify] Skipping segment {seg["segment_id"]} — '
                'speaker is UNKNOWN, classifier cannot verify'
            )
            continue

        words        = seg['text'].split()
        duration_s   = (seg['end_ms'] - seg['start_ms']) / 1000
        rate_wps     = len(words) / max(duration_s, 0.1)
        avg_word_len = sum(len(w) for w in words) / max(len(words), 1)

        pitch_mean, pitch_var, pause_ratio = (
            extract_acoustic_features(audio_path, seg['start_ms'], seg['end_ms'])
            if has_audio else (150.0, 20.0, 0.2)
        )
        to_classify.append((seg, [pitch_mean, pitch_var, rate_wps, pause_ratio, avg_word_len, duration_s]))

    if not to_classify:
        logger.info('[role_classify] No classifiable segments — skipping')
        return {**state, 'role_flags': []}

    # Single model call for all segments — replaces N individual predict() calls
    try:
        feature_rows   = [row for _, row in to_classify]
        predicted_roles = role_classify_batch(feature_rows)
    except Exception as e:
        logger.error(f'[role_classify] Batch classifier failed: {e}', exc_info=True)
        return {**state, 'role_flags': []}

    for (seg, _), predicted_role in zip(to_classify, predicted_roles):
        resolved_role = seg.get('speaker_role', '')

        if resolved_role:
            # Enrollment resolved this speaker — compare classifier against known role directly
            disagrees = predicted_role != resolved_role
        else:
            # No enrollment — fall back to SPEAKER_XX label heuristic
            diarized_label = seg.get('speaker', '')
            disagrees = (
                (predicted_role == 'DOCTOR'  and 'SPEAKER_1' in diarized_label) or
                (predicted_role == 'PATIENT' and 'SPEAKER_0' in diarized_label)
            )

        if disagrees:
            seg['role_flag'] = True
            role_flags.append(seg['segment_id'])
            update_segment_diarization(seg['segment_id'], seg['speaker'], role_flag=True)
            logger.warning(
                f'[role_classify] Disagreement on segment {seg["segment_id"]}: '
                f'classifier={predicted_role} resolved_role={resolved_role or seg.get("speaker", "?")}'
            )
        else:
            logger.debug(
                f'[role_classify] Segment {seg["segment_id"]}: '
                f'classifier={predicted_role} agrees with resolved_role={resolved_role or seg.get("speaker", "?")}'
            )

    logger.info(f'[role_classify] {len(role_flags)} role disagreements flagged')
    return {**state, 'role_flags': role_flags}


# ─── Node 4: LLM SOAP mapping ────────────────────────────────────────────────

def map_node(state: ScribeState) -> ScribeState:
    segments = state['segments']
    logger.info(f'[map] Mapping {len(segments)} segments to SOAP sections')

    try:
        mappings = map_segments(segments)
    except Exception as e:
        logger.error(f'[map] LLM mapping failed: {e}', exc_info=True)
        return state

    mapping_dict = {m['id']: m['soap_section'] for m in mappings}
    logger.debug(f'[map] LLM returned {len(mapping_dict)} mappings')

    for seg in segments:
        section = mapping_dict.get(str(seg.get('id', '')), 'UNCLASSIFIED')
        seg['soap_section'] = section
        update_segment_mapping(seg['segment_id'], section)
        logger.debug(f'[map] Segment {seg["segment_id"]} → {section}')

    section_counts = {}
    for seg in segments:
        s = seg.get('soap_section', 'UNCLASSIFIED')
        section_counts[s] = section_counts.get(s, 0) + 1
    logger.info(f'[map] SOAP distribution: {section_counts}')

    return {**state, 'mapped_segments': segments}


# ─── Node 5: PyTorch confidence rescorer ─────────────────────────────────────

def score_node(state: ScribeState) -> ScribeState:
    segments = state.get('mapped_segments', state['segments'])
    logger.info(f'[score] Scoring {len(segments)} segments')

    scored = []
    for seg in segments:
        try:
            reliability = rescore(
                asr_confidence=seg.get('confidence', 1.0),
                token_count=len(seg['text'].split()),
                soap_section=seg.get('soap_section', 'S')
            )
        except Exception as e:
            logger.error(
                f'[score] Rescorer failed on segment {seg["segment_id"]}: {e}',
                exc_info=True
            )
            reliability = 0.5  # neutral fallback

        seg['reliability_score'] = reliability
        seg['confidence_flag']   = reliability < 0.6
        update_segment_score(seg['segment_id'], reliability, reliability < 0.6)

        if seg['confidence_flag']:
            logger.warning(
                f'[score] Low reliability: segment {seg["segment_id"]} '
                f'score={reliability:.2f} text="{seg["text"][:60]}"'
            )
        else:
            logger.debug(
                f'[score] Segment {seg["segment_id"]} score={reliability:.2f}'
            )

        scored.append(seg)

    flagged = [s for s in scored if s['confidence_flag']]
    logger.info(f'[score] {len(flagged)}/{len(scored)} segments flagged as low confidence')

    return {**state, 'scored_segments': scored}


# ─── Node 6: Package + audio deletion ────────────────────────────────────────

def package_node(state: ScribeState) -> ScribeState:
    session_id = state['session_id']
    segments   = state.get('scored_segments', state['segments'])

    logger.info(f'[package] Building review payload for {len(segments)} segments')

    soap: dict = {'S': [], 'O': [], 'A': [], 'P': [], 'UNCLASSIFIED': []}
    for seg in segments:
        section = seg.get('soap_section', 'UNCLASSIFIED')
        soap.setdefault(section, []).append(seg)

    unknown_speaker_segs = [s for s in segments if s.get('speaker_confidence_flag')]
    role_flagged_segs    = [s for s in segments if s.get('role_flag')]
    low_confidence_segs  = [s for s in segments if s.get('confidence_flag')]

    payload = {
        'session_id':    session_id,
        'soap':          soap,
        'role_flags':    state.get('role_flags', []),
        'speaker_unknown_ids': state.get('speaker_unknown_ids', []),
        'flagged_count': sum(1 for s in segments if (
            s.get('confidence_flag') or s.get('role_flag') or s.get('speaker_confidence_flag')
        )),
        'stats': {
            'total_segments':           len(segments),
            'speaker_unknown_count':    len(unknown_speaker_segs),
            'role_disagreement_count':  len(role_flagged_segs),
            'low_asr_confidence_count': len(low_confidence_segs),
        }
    }

    logger.info(
        f'[package] Payload built — total={len(segments)} '
        f'speaker_unknown={len(unknown_speaker_segs)} '
        f'role_flags={len(role_flagged_segs)} '
        f'low_confidence={len(low_confidence_segs)}'
    )

    # ── HIPAA: delete WAV after pipeline is done with it ─────────────────────
    audio_path = os.path.join(AUDIO_DIR, f'{session_id}.wav')
    if os.path.exists(audio_path):
        try:
            os.unlink(audio_path)
            logger.info(f'[package] Audio deleted post-pipeline (HIPAA compliance): {audio_path}')
        except Exception as e:
            logger.error(
                f'[package] FAILED to delete audio file {audio_path}: {e} '
                '— manual cleanup required',
                exc_info=True
            )
    else:
        logger.debug(f'[package] Audio file not found at {audio_path} — already deleted or never created')

    return {**state, 'review_payload': payload}
