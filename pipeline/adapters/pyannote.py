from pyannote.audio import Pipeline
import os

# DEFAULT diarization — offline, no PHI leaves the device
# Requires a HuggingFace token to download the model on first run
# Get one at: https://huggingface.co/pyannote/speaker-diarization-3.1

_pipeline = None

def _load():
    global _pipeline
    hf_token = os.environ.get('HUGGINGFACE_TOKEN')
    _pipeline = Pipeline.from_pretrained(
        'pyannote/speaker-diarization-3.1',
        use_auth_token=hf_token
    )
    print('[pyannote] Model loaded')


def diarize(audio_path: str) -> list[dict]:
    """
    Run 2-speaker diarization on the session audio file.
    Returns: [{ start_ms, end_ms, speaker_label }]
    """
    global _pipeline
    if _pipeline is None:
        _load()

    diarization = _pipeline(audio_path, num_speakers=2)

    windows = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        windows.append({
            'start_ms': int(turn.start * 1000),
            'end_ms': int(turn.end * 1000),
            'speaker_label': speaker   # 'SPEAKER_00' or 'SPEAKER_01'
        })

    return windows
