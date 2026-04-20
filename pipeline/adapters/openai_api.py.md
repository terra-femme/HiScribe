# openai_api.py — Sends transcript segments to GPT-4o-mini to classify them into SOAP sections

## What This File Is For
This file is responsible for asking an LLM (Large Language Model) which SOAP section each transcript segment belongs to. It constructs a carefully designed prompt, calls the OpenAI API, and validates the response before returning it. Critically, the LLM is instructed only to *classify* — it must never rewrite, summarize, or generate clinical content. This is a very deliberate safety boundary for a medical application.

## How It Fits In The Project
This file is imported by `adapters/llm.py` (the switchboard adapter), which re-exports its `map_segments` function. `graph/nodes.py` calls `map_segments(segments)` in the `map_node` step of the pipeline. The LLM never sees the audio — it only sees the text transcription with speaker labels.

## Line-by-Line Breakdown

### Lines 1–3 — Imports
```python
import json
import os
from openai import OpenAI
```
**What it does:** Imports `json` for encoding the segment list into the prompt and decoding the LLM's response, `os` for reading the API key from the environment, and the OpenAI Python client.
**Why:** The OpenAI Python library handles authentication, HTTP, retries, and response parsing. Using the official client is always preferable to making raw HTTP calls.
**ELI5:** You're using the official phone number for OpenAI instead of trying to find their IP address and calling them yourself.
**Best practice:** Never hardcode an API key in source code. Always read it from the environment (`os.environ['OPENAI_API_KEY']`).

---

### Lines 5–11 — Lazy client initialization
```python
_client = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
    return _client
```
**What it does:** Uses the same lazy initialization pattern as pyannote. The `OpenAI` client is created on first use, not at import time. `os.environ['OPENAI_API_KEY']` reads the API key from the environment (will raise `KeyError` if missing).
**Why:** Creating the client at import time would cause a crash if the env var isn't set yet (e.g., during testing or before `load_dotenv()` runs). Lazy initialization gives `load_dotenv()` time to run first.
**ELI5:** Rather than setting the table before you know if guests are coming, you wait until the first guest arrives and then set the table.
**Best practice:** Using `os.environ['OPENAI_API_KEY']` (bracket access) instead of `.get()` is intentional here — if the key is missing, a clear `KeyError` crash is better than silently passing `None` as an API key and getting a confusing authentication error later.

---

### Lines 14–31 — The MAP_PROMPT template
```python
MAP_PROMPT = """You are a clinical documentation assistant. You will receive a list of transcript segments
from a medical visit. Each segment has a speaker label (DOCTOR or PATIENT) and the exact words spoken.

Your job is to assign each segment to exactly one SOAP section:
- S (Subjective): patient's own words about symptoms, history, complaints
- O (Objective): clinician's observations, measurements, exam findings
- A (Assessment): clinician's diagnosis or clinical judgment
- P (Plan): clinician's instructions, orders, referrals, follow-up

Rules:
- Do NOT paraphrase, summarize, or rewrite any segment
- Do NOT add any words not present in the original segment
- Do NOT combine segments
- If a segment clearly belongs to no section, assign: "UNCLASSIFIED"
- Return ONLY a JSON array: [{{"id": "...", "soap_section": "S|O|A|P|UNCLASSIFIED"}}]

Segments:
{segments}"""
```
**What it does:** Defines the system prompt template. `{segments}` is a placeholder that will be filled in with the actual segment data when the prompt is formatted. The double curly braces `{{` and `}}` are how you write literal `{` and `}` characters inside a Python format string.
**Why:** The prompt is highly specific about what the LLM must NOT do (paraphrase, summarize, generate). In clinical documentation, the LLM acting as a classifier (labeler) rather than a generator (writer) is a critical safety distinction. The LLM should never put words in a patient's mouth.
**ELI5:** You're giving a librarian a stack of books and asking them to sort them into genres. You're explicitly telling them: "do NOT rewrite the books — just categorize them."
**Best practice:** Prompt engineering is the process of crafting instructions that reliably produce consistent outputs. The "Rules" section is essential for preventing hallucinations or overreach. Putting the constraints in a numbered list inside the prompt is more reliable than expecting the model to infer them.

---

### Line 34 — Valid section set
```python
VALID_SECTIONS = {'S', 'O', 'A', 'P', 'UNCLASSIFIED'}
```
**What it does:** Defines the complete set of valid SOAP section values. Used in the validation function to reject any value the LLM made up.
**Why:** Using a `set` (curly braces) instead of a `list` makes the `in` membership check O(1) instead of O(n). For only 5 values this doesn't matter much, but it is the correct habit.
**ELI5:** The bouncer at the door has a list of 5 valid names. Anyone not on the list gets turned away.
**Best practice:** Define constants like this at the module level, not inside the function that uses them. This makes them easy to find, change, and reuse.

---

### Lines 37–77 — _validate_mappings()
```python
def _validate_mappings(raw: list, original_segments: list[dict]) -> list[dict]:
    """
    Validates LLM output before it touches the DB.
    - Each item must have 'id' (str) and 'soap_section' (valid value)
    - Any item missing or malformed defaults to UNCLASSIFIED
    - Any input segment not present in the LLM response gets UNCLASSIFIED
    """
    valid_ids = {str(seg['id']) for seg in original_segments}
    seen_ids = set()
    result = []

    if not isinstance(raw, list):
        print(f'[llm] Validation failed — expected list, got {type(raw).__name__}. Defaulting all to UNCLASSIFIED.')
        return [{'id': seg['id'], 'soap_section': 'UNCLASSIFIED'} for seg in original_segments]

    for item in raw:
        if not isinstance(item, dict):
            print(f'[llm] Skipping non-dict item in LLM response: {item}')
            continue

        item_id = str(item.get('id', ''))
        section = item.get('soap_section', 'UNCLASSIFIED')

        if item_id not in valid_ids:
            print(f'[llm] Skipping unknown segment id: {item_id}')
            continue

        if section not in VALID_SECTIONS:
            print(f'[llm] Invalid soap_section "{section}" for id {item_id} — defaulting to UNCLASSIFIED')
            section = 'UNCLASSIFIED'

        seen_ids.add(item_id)
        result.append({'id': item_id, 'soap_section': section})

    # Any segment the LLM didn't return gets UNCLASSIFIED
    for seg in original_segments:
        if str(seg['id']) not in seen_ids:
            print(f'[llm] Segment {seg["id"]} missing from LLM response — defaulting to UNCLASSIFIED')
            result.append({'id': str(seg['id']), 'soap_section': 'UNCLASSIFIED'})

    return result
```
**What it does:** Takes the raw LLM output and scrubs it clean before any of it reaches the database. Handles four failure cases: the whole response is not a list; an individual item is not a dict; an item references an ID we didn't send; an item has an unrecognized section value.
**Why:** LLMs are probabilistic — even with a perfect prompt, they occasionally produce unexpected output. This guard means the pipeline never writes garbage to the database, no matter what the LLM returns. Every failure path produces a safe default (`UNCLASSIFIED`).
**ELI5:** Imagine you asked someone to fill out a form. Before you file it, you check that every field is actually filled in and contains valid values. If something is wrong, you write "unknown" rather than filing a broken form.
**Best practice:** Validating LLM output before it reaches any data store is non-negotiable in production systems. The three `print` statements are lightweight telemetry — in production, these should be proper structured log entries (e.g. using the `logging` module) at the WARNING level.

---

### Lines 80–111 — map_segments()
```python
def map_segments(segments: list[dict]) -> list[dict]:
    """
    Maps each segment to a SOAP section.
    Returns list of { id, soap_section }.
    The LLM classifies — it does not rewrite, paraphrase, or generate any clinical content.
    """
    client = _get_client()

    segment_input = [
        {'id': str(seg.get('id', i)), 'speaker': seg.get('speaker', 'UNKNOWN'), 'text': seg['text']}
        for i, seg in enumerate(segments)
    ]

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {'role': 'user', 'content': MAP_PROMPT.format(segments=json.dumps(segment_input, indent=2))}
        ],
        temperature=0,
        response_format={'type': 'json_object'}
    )

    content = response.choices[0].message.content
    parsed = json.loads(content)

    # Handle both { mappings: [...] } and direct array responses
    if isinstance(parsed, list):
        raw = parsed
    else:
        raw = parsed.get('mappings', parsed.get('segments', []))

    return _validate_mappings(raw, segment_input)
```
**What it does:** The public function. Builds a clean segment list (id, speaker, text), formats it into the prompt, calls GPT-4o-mini with `temperature=0` and JSON mode enforced, parses the response, and validates it before returning.
**Why:** `temperature=0` means the model picks the highest-probability output every time — no creativity or randomness. This is correct for a classification task where you want deterministic, consistent results. `response_format={'type': 'json_object'}` forces the model to respond with valid JSON.
**ELI5:** You're asking a very meticulous assistant to sort cards into piles. "Temperature 0" means they always sort the same way, without getting creative. "JSON mode" means they have to write their answer on a standardized form.
**Best practice:** The try/except for JSON parsing is implicit here — `json.loads()` will raise `json.JSONDecodeError` if the content isn't valid JSON. Consider wrapping it in a try/except to handle this gracefully and default to UNCLASSIFIED for all segments rather than crashing.

### Lines 104–109 — Handling ambiguous JSON shapes
```python
if isinstance(parsed, list):
    raw = parsed
else:
    raw = parsed.get('mappings', parsed.get('segments', []))
```
**What it does:** Handles the case where the model returns either a raw array `[...]` or wraps it in an object like `{"mappings": [...]}`. Both are extracted correctly.
**Why:** Even with `response_format={'type': 'json_object'}`, the OpenAI API requires the top-level response to be an object (not an array). The model may wrap the array in different keys. This code tries the two most common key names.
**ELI5:** You asked for a gift in a box. Sometimes the box is labeled "mappings," sometimes "segments." Either way, you open the box and take what's inside.
**Best practice:** This is pragmatic defensive programming. Document the expected shapes explicitly, and log any unexpected formats so you can improve the prompt over time.

## Common Mistakes
1. **Not checking `VALID_SECTIONS` and trusting the LLM blindly.** LLMs can return `"Subjective"` instead of `"S"`, or invent a section called `"History"`. Always validate every output field.
2. **Using `temperature > 0` for classification tasks.** Higher temperature introduces randomness, meaning the same segment might be assigned a different section each time. Always use `temperature=0` for deterministic classification.
3. **Forgetting to handle the `json.loads()` failure case.** Even with JSON mode enabled, network interruptions, API errors, or unexpected model behavior can return non-JSON content. Wrap `json.loads()` in a try/except.

## Key Concepts To Look Up
- SOAP note format (Subjective, Objective, Assessment, Plan)
- OpenAI `chat.completions.create` parameters: `model`, `messages`, `temperature`, `response_format`
- Prompt engineering: system prompts, constraints, output format specification
- LLM hallucination and why validation of model output is critical
- JSON mode in the OpenAI API
- Set membership testing in Python (`in` with a set vs a list)
- Defensive programming patterns for unreliable external services
