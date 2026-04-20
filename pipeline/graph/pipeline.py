import asyncio
import logging

from langgraph.graph import StateGraph
from .nodes import (
    ScribeState,
    finalize_node,
    diarize_node,
    resolve_speakers_node,
    role_classify_node,
    map_node,
    score_node,
    package_node
)

logger = logging.getLogger('hiscribe.pipeline')

# Build the LangGraph state machine
_graph = StateGraph(ScribeState)

_graph.add_node('finalize',         finalize_node)
_graph.add_node('diarize',          diarize_node)
_graph.add_node('resolve_speakers', resolve_speakers_node)
_graph.add_node('role_classify',    role_classify_node)
_graph.add_node('map',              map_node)
_graph.add_node('score',            score_node)
_graph.add_node('package',          package_node)

_graph.set_entry_point('finalize')
_graph.add_edge('finalize',         'diarize')
_graph.add_edge('diarize',          'resolve_speakers')
_graph.add_edge('resolve_speakers', 'role_classify')
_graph.add_edge('role_classify',    'map')
_graph.add_edge('map',           'score')
_graph.add_edge('score',         'package')
_graph.set_finish_point('package')

_app = _graph.compile()


async def run_pipeline(session_id: str) -> dict:
    logger.info(f'[pipeline] Starting for session {session_id}')
    initial_state: ScribeState = {
        'session_id':          session_id,
        'segments':            [],
        'role_flags':          [],
        'speaker_unknown_ids': [],
        'speaker_map':         {},   # populated by resolve_speakers_node if providers enrolled
        'mapped_segments':     [],
        'scored_segments':     [],
        'review_payload':      {}
    }
    # Run the synchronous LangGraph DAG in a thread pool so it does not
    # block the FastAPI event loop during potentially long pipeline runs
    # (pyannote diarization can take 10–30 minutes on CPU for long sessions).
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _app.invoke, initial_state)
    logger.info(f'[pipeline] Complete for session {session_id}')
    return result['review_payload']
