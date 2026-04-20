# nodes.py — The six processing steps that transform a raw session into a structured clinical note

## What This File Is For
This file defines all six "nodes" of the HiScribe processing pipeline. Each node is a function that receives the current state of a session, does one specific job (like loading segments, running speaker detection, or assigning SOAP sections), and returns an updated state. Together they form an assembly line: raw transcript in, structured clinical note out.

## How It Fits In The Project
`nodes.py` is the engine room of the pipeline. `graph/pipeline.py` imports all six node functions from this file and wires them together into a directed graph. Each node imports from the adapter and model layers below it: `db/sqlite.py` for database reads/writes, `adapters/diarize.py` for speaker detection, `adapters/llm.py` for SOAP classification, and the two ML model inference files for scoring and role classification.

## Line-by-Line Breakdown

### Lines 1–2 — Standard library imports
```python
from typing import TypedDict, List
import os
```
**What it does:** Imports `TypedDict` (for defining the shape of the pipeline state dictionary) and `List` (for type hints on lists), plus `os` for file path construction.
**Why:** `TypedDict` lets you create a dictionary with named, typed fields — this is the backbone of LangGraph's state management. Type hints don't enforce anything at runtime, but they make the code far easier to read and catch bugs in editors like VS Code.
**ELI5:** `TypedDict` is like a form with labeled fields. Instead of a blank dictionary where anything goes, it tells Python exactly what keys are expected and what type each value should be. In LangGraph, TypedDict serves as the backbone of state management because it provides a structured, shared schema that acts as the "memory" flowing between nodes in a graph. While it doesn't enforce types at runtime, it allows developers to define exactly what data (messages, flags, results) should exist at any given point in a workflow.
**Best practice:** In Python 3.9+, you can use `list[dict]` instead of `List[dict]` from `typing`. The `from typing import List` form is the older style but still valid everywhere.

---

### Lines 4–11 — Internal imports
```python
from db.sqlite import (
    get_segments, update_segment_diarization,
    update_segment_mapping, update_segment_score
)
from adapters.diarize import diarize
from adapters.llm import map_segments
from models.confidence_rescorer.infer import score as rescore
from models.role_classifier.infer import classify as role_classify
```
**What it does:** Imports the four database functions needed by the nodes, plus the three processing adapters/models. The `as rescore` and `as role_classify` aliases rename the imported functions to avoid name collisions.
**Why:** Each node should import only what it needs. Grouping these at the top follows Python's PEP 8 style guide (standard library first, then third-party, then internal).
**ELI5:** Before cooking, you gather all your ingredients on the counter. These imports are gathering all the tools each node will need.
**Best practice:** Using `as` to alias imports is normal and encouraged when the default name conflicts with a local variable or is too generic (e.g. `score` vs `rescore` clarifies the purpose).

---

### Line 13 — Audio directory path
```python
AUDIO_DIR = os.path.join(os.path.dirname(__file__), '../../data/audio')
```
**What it does:** Builds an absolute path to the `data/audio` folder by starting from this file's location (`__file__`) and navigating two directories up.
**Why:** Hardcoding `'data/audio'` would be a relative path that breaks depending on where you run the script from. Using `__file__` makes the path relative to the source file itself, not the shell's working directory.
**ELI5:** Imagine giving someone directions from your front door, not from some random point in the city. `__file__` is your front door.
**Best practice:** Always construct paths with `os.path.join` rather than string concatenation with `/` or `\\`. It works on all operating systems.

---

### Lines 16–22 — ScribeState TypedDict
```python
class ScribeState(TypedDict):
    session_id: str
    segments: List[dict]
    role_flags: List[str]           # segment_ids where diarization + classifier disagree
    mapped_segments: List[dict]     # adds: soap_section per segment
    scored_segments: List[dict]     # adds: reliability_score, flags
    review_payload: dict
```
**What it does:** Defines the shape of the data that flows through the entire pipeline. Every node receives this dictionary and returns an updated version of it.
**Why:** LangGraph requires a typed state definition. This `TypedDict` acts as a contract — every node knows exactly what fields exist and what type they are.
**ELI5:** Think of `ScribeState` as a clipboard that gets passed from worker to worker down an assembly line. Each worker reads what they need from the clipboard and writes their results back onto it.
**Best practice:** Notice how the comments document the progression — `segments` holds raw data, `mapped_segments` adds `soap_section`, `scored_segments` adds `reliability_score`. Documenting what each stage adds makes the data flow easy to trace.

---

### Lines 25–30 — Node 1: finalize_node
```python
def finalize_node(state: ScribeState) -> ScribeState:
    session_id = state['session_id']
    segments = get_segments(session_id)
    print(f'[finalize] {len(segments)} segments loaded for session {session_id}')
    return {**state, 'segments': segments}
```
**What it does:** Reads all finalized (fully transcribed) segments for this session from the database and stores them in the state.
**Why:** This is the first node — it populates the state with the raw data that all subsequent nodes will process. "Finalized" means the real-time transcription stream has ended and the segments are marked `is_final = 1` in the database.
**ELI5:** Before a chef can cook a meal, they need to gather all the ingredients. This node "gathers" all the transcript pieces.
**Best practice:** `{**state, 'segments': segments}` is the idiomatic LangGraph pattern for returning an updated state. The `**state` unpacks all existing keys, and `'segments': segments` overwrites just that one key. Never mutate the state dict in place — always return a new dict.
**Note on Name**:   The function is called finalize_node because it finalizes the input to the pipeline — not the output. During the
  recording session, transcript segments were being written to the DB in real-time as they came in from the ASR. Some
  were partial, some were final. This node goes and fetches only the finalized segments (the confirmed ones, not the
  partials) and loads them into the graph state so the rest of the pipeline can work on them.
So the name refers to the kind of segments it's collecting — finalized/confirmed transcripts — not its position or role in the workflow.
  A clearer name might have been load_node or fetch_segments_node, but finalize_node captures the intent of "we're done
  recording, now lock in the final segments." It's naming from the domain perspective (finalize the audio pass) rather than the technical perspective (load data).

---

### Lines 33–53 — Node 2: diarize_node
```python
def diarize_node(state: ScribeState) -> ScribeState:
    session_id = state['session_id']
    audio_path = os.path.join(AUDIO_DIR, f'{session_id}.wav')

    if not os.path.exists(audio_path):
        print(f'[diarize] No audio file found for {session_id} — skipping diarization')
        return state

    diarization = diarize(audio_path)

    segments = state['segments']
    for seg in segments:
        label = _match_speaker(seg['start_ms'], seg['end_ms'], diarization)
        seg['speaker'] = label
        update_segment_diarization(seg['segment_id'], label, role_flag=False)

    print(f'[diarize] Labels assigned for {len(segments)} segments')
    return {**state, 'segments': segments}
```
**What it does:** Checks if an audio file exists for the session, runs speaker diarization on it (which identifies who is speaking when), then matches each transcript segment to a speaker label by its timestamp.
**Why:** Diarization tells us whether SPEAKER_00 or SPEAKER_01 is talking at any given moment. This is essential for understanding which parts of the conversation came from the doctor vs the patient. <br>
**ELI5:** Imagine a conversation transcript without names — just words. Diarization is like watching the video recording and writing "Alice said" or "Bob said" next to each line. <br>
**Best practice:** The graceful fallback (`return state` if no audio file exists) is the right pattern. A node should never crash the whole pipeline because of optional input. Always handle the missing-data case explicitly. <br>
**Note: ❯** so state['segments'] comes straight from this functional block right? not anywhere else? because what did node.js kick off again that i couldnt locate i forgot: <br>
● Two separate things are happening in that function — this is the key confusion.

  ---
  state['segments'] — Where It Comes From

  Not from diarize_node itself. It was already in state before this function ran.

  The node that populated it was finalize_node — the one before it in the DAG:

  def finalize_node(state: ScribeState) -> ScribeState:
      segments = get_segments(session_id)   # ← reads from SQLite
      return {**state, 'segments': segments}  # ← puts them in state

  By the time diarize_node runs, state['segments'] is already a full list of dicts. diarize_node just reads them, loops
  over them, mutates them by adding seg['speaker'], and returns them back.

  ---
  What Node.js Kicked Off

  Node.js did two separate things that both feed into diarize_node:

  Thing 1 — wrote the segments to SQLite during recording:
  Browser mic → WebSocket → gateway → Gladia ASR
      → onSegment() callback
          → saveSegment() writes to SQLite
              { text, start_ms, end_ms, confidence, is_final=1 }
  This is what state['segments'] ultimately contains — those rows written during the live session.

  Thing 2 — triggered the pipeline after recording ended:
  Browser clicks "Stop"
      → POST /session/:id/end  (session.ts:87)
          → fetch('http://localhost:8000/pipeline/run', { session_id })
              → run_pipeline(session_id)  (pipeline.py)
                  → LangGraph starts → finalize_node → diarize_node → ...

  So Node.js is responsible for both the data inside state (wrote the segments during recording) and the trigger that
  started the pipeline (HTTP call when recording stopped). By the time Python runs, Node.js has already done its job and
   stepped aside.
---

### Lines 56–61 — Helper: _match_speaker
```python
def _match_speaker(start_ms: int, end_ms: int, diarization: list) -> str:
    mid = (start_ms + end_ms) / 2
    for window in diarization:
        if window['start_ms'] <= mid <= window['end_ms']:
            return window['speaker_label']
    return 'SPEAKER_0'
```
**What it does:** Given a segment's start and end timestamps (in milliseconds), finds which diarization window contains the midpoint of that segment and returns the speaker label. Defaults to `'SPEAKER_0'` if no window matches.
**Why:** Transcript segments and diarization windows come from different systems and may not align perfectly at their edges. Using the midpoint is a robust heuristic — a segment is "owned" by whichever speaker holds the middle of it.
**ELI5:** If someone is talking from 0 to 10 seconds, and a transcript segment runs from 4 to 8 seconds, the midpoint is 6. It falls inside the 0–10 window, so we say that speaker "owns" this segment.
**Best practice:** The underscore prefix (`_match_speaker`) is a Python convention indicating this is a private/internal helper not intended to be imported elsewhere.

---

### Lines 64–96 — Node 3: role_classify_node
```python
def role_classify_node(state: ScribeState) -> ScribeState:
    segments = state['segments']
    role_flags = []

    for seg in segments:
        pitch_mean = 150.0    # placeholder — wire to librosa in production
        pitch_var = 20.0
        rate_wps = len(seg['text'].split()) / max((seg['end_ms'] - seg['start_ms']) / 1000, 0.1)
        pause_ratio = 0.2
        avg_word_len = sum(len(w) for w in seg['text'].split()) / max(len(seg['text'].split()), 1)
        duration_s = (seg['end_ms'] - seg['start_ms']) / 1000

        predicted_role = role_classify(pitch_mean, pitch_var, rate_wps, pause_ratio, avg_word_len, duration_s)
        diarized_role = seg.get('speaker', 'SPEAKER_0')

        disagrees = False
        if predicted_role == 'DOCTOR' and 'SPEAKER_1' in diarized_role:
            disagrees = True
        elif predicted_role == 'PATIENT' and 'SPEAKER_0' in diarized_role:
            disagrees = True

        if disagrees:
            seg['role_flag'] = True
            role_flags.append(seg['segment_id'])
            update_segment_diarization(seg['segment_id'], seg['speaker'], role_flag=True)

    print(f'[role_classify] {len(role_flags)} role disagreements flagged')
    return {**state, 'role_flags': role_flags}
```
**What it does:** For every segment, extracts acoustic features (some real, some placeholders), runs the TensorFlow role classifier to predict DOCTOR or PATIENT, then compares that prediction to the diarization label. When they disagree, the segment is flagged for provider review.
**Why:** Diarization only knows "Speaker 0" and "Speaker 1" — it doesn't know which is the doctor. The role classifier uses acoustic features to make that identification independently, providing a cross-check.
**ELI5:** Two different security guards check your badge. If they both say "yes," great. If one says "yes" and the other says "no," a supervisor (the provider) needs to look into it.
**Best practice:** The `# placeholder` comments are honest and important. Production code should replace `pitch_mean = 150.0` with real librosa extraction. Stubs with clear TODOs are better than silently wrong values.

---

### Lines 100–113 — Node 4: map_node
```python
def map_node(state: ScribeState) -> ScribeState:
    segments = state['segments']
    mappings = map_segments(segments)

    mapping_dict = {m['id']: m['soap_section'] for m in mappings}

    for seg in segments:
        section = mapping_dict.get(str(seg.get('id', '')), 'UNCLASSIFIED')
        seg['soap_section'] = section
        update_segment_mapping(seg['segment_id'], section)

    print(f'[map] SOAP sections assigned for {len(segments)} segments')
    return {**state, 'mapped_segments': segments}
```
**What it does:** Sends all segments to the LLM (via `map_segments`), which assigns each one to a SOAP section (Subjective, Objective, Assessment, Plan, or Unclassified). Stores the result in both the state and the database.
**Why:** SOAP is the standard format for medical notes. Organizing the transcript by SOAP section makes it immediately usable for clinical documentation.
**ELI5:** After the chef gathers ingredients, this step sorts them into categories: proteins, vegetables, spices. The LLM is the chef deciding which ingredient goes in which pile.
**Best practice:** Converting the mappings list to a dictionary (`mapping_dict`) before the loop is efficient — it turns O(n²) lookups into O(n). Always prefer a dict lookup over searching through a list in a loop.

---

### Lines 116–134 — Node 5: score_node
```python
def score_node(state: ScribeState) -> ScribeState:
    segments = state.get('mapped_segments', state['segments'])
    scored = []

    for seg in segments:
        reliability = rescore(
            asr_confidence=seg.get('confidence', 1.0),
            token_count=len(seg['text'].split()),
            soap_section=seg.get('soap_section', 'S')
        )
        seg['reliability_score'] = reliability
        seg['confidence_flag'] = reliability < 0.6
        update_segment_score(seg['segment_id'], reliability, reliability < 0.6)
        scored.append(seg)

    flagged = [s for s in scored if s['confidence_flag']]
    print(f'[score] {len(flagged)} segments flagged as low confidence')
    return {**state, 'scored_segments': scored}
```
**What it does:** Runs each segment through the PyTorch confidence re-scorer, which returns a number between 0 and 1 representing how reliable the transcription is. Segments scoring below 0.6 are flagged for review.<br>
**Why:** ASR systems are not perfect. Some segments may have been captured in noisy conditions or contain uncommon medical terms. The reliability score helps the provider know which segments need the closest scrutiny. <br>
**ELI5:** Like a spell-checker that shows you which words it is less sure about, highlighted in yellow. <br>
**Best practice:** `state.get('mapped_segments', state['segments'])` gracefully falls back to `segments` if the `mapped_segments` key is somehow empty. This defensive coding prevents a crash if a previous node didn't populate its output. <br>
**Note** ❯ so rescorer uses pytorch on the nodes.py through the models import? Yes <br>
  nodes.py <br>
    └── from models.confidence_rescorer.infer import score as rescore   (line 8)<br>
          └── infer.py<br>
                └── import torch                                          (line 1)<br>
                └── from .model import ConfidenceRescorer                 (line 3)<br><br>
                └── _model.load_state_dict(torch.load('weights.pt'))      (line 15)
<br>
  And in score_node (nodes.py):<br>

  reliability = rescore(<br>
      asr_confidence=seg.get('confidence', 1.0),<br>
      token_count=len(seg['text'].split()),<br>
      soap_section=seg.get('soap_section', 'S')<br>
  )<br>

  So nodes.py calls rescore(), which is just score() from infer.py renamed on import. That function:<br>

  1. Lazy-loads the PyTorch model on first call
  2. Builds a 6-element input tensor — [asr_confidence, token_count, S, O, A, P] where the last 4 are a one-hot encoding
   of the SOAP section
  3. Runs it through the model with torch.no_grad() (inference mode, no gradient tracking)
  4. Returns a single float [0, 1] — the reliability score<br>

  The PyTorch model never gets called directly from nodes.py. nodes.py only knows about rescore(). The fact that PyTorch is underneath is completely hidden inside infer.py — that's the point of the adapter layer.<br>

❯ what does lazy load mean<br>

● Lazy load means "don't load it until the first time you actually need it."<br>

  ---
  The Opposite First — Eager Loading

  If the model loaded at import time (eager), this is what it would look like:

  # infer.py — EAGER
  import torch
  from .model import ConfidenceRescorer

  # This runs the MOMENT any file does `import infer`
  _model = ConfidenceRescorer()
  _model.load_state_dict(torch.load('weights.pt'))
  _model.eval()

  The second Python sees import infer, it immediately loads a PyTorch model into memory. Even if you never call score()
  in that session. Even during server startup. Even if you're just running a quick test.

  ---
  What Lazy Loading Does Instead

  # infer.py — LAZY
  _model = None          # ← just a placeholder, nothing loaded yet

  def _load():
      global _model
      _model = ConfidenceRescorer()
      _model.load_state_dict(torch.load('weights.pt'))
      _model.eval()

  def score(asr_confidence, token_count, soap_section):
      if _model is None:   # ← first time score() is called, _model is still None
          _load()          # ← NOW it loads, and only now
      ...

  _model = None is just a empty parking spot. The actual 加载 only happens the first time score() is called. Every call
  after that, _model is already loaded so _load() is skipped.

  ---
  Real World Analogy

  Lazy load is like a vending machine that doesn't stock itself until someone actually presses a button. Eager load is
  stocking every slot the moment the machine is plugged in — even the flavors nobody orders.

  ---
  Why It Matters Here

  PyTorch models are heavy — loading weights.pt takes a few seconds and occupies RAM. If the server starts up and loads
  both the PyTorch rescorer AND the TensorFlow role classifier immediately, startup is slow and memory is consumed
  whether or not a session ever runs.

  With lazy loading:
  - Server starts instantly
  - First session after startup is slightly slower (model loads on first call)
  - Every session after that is fast (model is cached in _model)

  The dev guide actually flags this as something to fix for production — call _load() during server startup so the first
   real patient session doesn't take the hit.

---

### Lines 137–154 — Node 6: package_node
```python
def package_node(state: ScribeState) -> ScribeState:
    segments = state.get('scored_segments', state['segments'])

    soap: dict = {'S': [], 'O': [], 'A': [], 'P': [], 'UNCLASSIFIED': []}
    for seg in segments:
        section = seg.get('soap_section', 'UNCLASSIFIED')
        soap.setdefault(section, []).append(seg)

    payload = {
        'session_id': state['session_id'],
        'soap': soap,
        'role_flags': state.get('role_flags', []),
        'flagged_count': sum(1 for s in segments if s.get('confidence_flag') or s.get('role_flag'))
    }

    print(f'[package] Review payload built — {len(segments)} segments across {sum(len(v) for v in soap.values())} sections')
    return {**state, 'review_payload': payload}
```
**What it does:** The final node. Takes all scored segments and assembles them into the review payload — a structured dictionary organized by SOAP section, including flags for any problematic segments.
**Why:** The payload is what gets returned to the frontend. Organizing segments by SOAP section makes the data immediately ready to render in the review UI without any further transformation.
**ELI5:** After the assembly line, this node packs the finished product into a box, labels it, and puts it on the shipping dock.
**Best practice:** `soap.setdefault(section, []).append(seg)` is a clean way to build a dict of lists — if the key doesn't exist yet, create it with an empty list, then append. It avoids a more verbose `if section not in soap: soap[section] = []` pattern.

## Common Mistakes
1. **Mutating the state dict in place without returning a new dict.** LangGraph expects nodes to return a dictionary. If you do `state['segments'] = segments` and return `state`, it might work but is against the pattern. Always use `{**state, 'key': new_value}`.
2. **Forgetting the graceful fallback in `diarize_node`.** If the audio file doesn't exist and you don't check, `diarize()` will crash with a FileNotFoundError and kill the whole pipeline.
3. **Confusing `segment_id` and `id`.** The database uses `segment_id` as the primary identifier, but `map_node` uses the row's integer `id` to match LLM responses. These are different fields and mixing them up causes silent mismatches.

## Key Concepts To Look Up
- `TypedDict` in Python's `typing` module
- LangGraph state management and node contracts
- Speaker diarization (what it is and how it differs from transcription)
- SOAP note format in medical documentation
- One-hot encoding (used in the score_node for SOAP sections)
- The midpoint heuristic for timestamp matching
- `dict.setdefault()` method
- `**` dictionary unpacking syntax in Python
