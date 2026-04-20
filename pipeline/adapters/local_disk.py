import os

AUDIO_DIR = os.path.join(os.path.dirname(__file__), '../../data/audio')

def get_audio_path(session_id: str) -> str:
    return os.path.normpath(os.path.join(AUDIO_DIR, f'{session_id}.wav'))
