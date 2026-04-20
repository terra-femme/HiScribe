# llm.py — A switchboard that controls which LLM provider the pipeline uses for SOAP classification

## What This File Is For
This file is another re-export adapter, identical in purpose to `diarize.py`. It imports `map_segments` from the currently active LLM provider (`openai_api.py`) and makes it available as `map_segments` from this module. The rest of the codebase imports from here, not from `openai_api.py` directly, so switching to a different LLM requires changing one line.

## How It Fits In The Project
`graph/nodes.py` imports `map_segments` from this file (`from adapters.llm import map_segments`). This file then forwards that import to `adapters/openai_api.py`. The commented-out lines document two alternative providers: Azure OpenAI and Vertex AI (Google Cloud).

## Line-by-Line Breakdown

### Line 1 — Comment explaining the pattern
```python
# Active re-export — change this ONE LINE to swap LLM provider
```
**What it does:** Documents the intent of this file in one line.
**Why:** Without this comment, a reader unfamiliar with the adapter pattern might wonder why a file with a single import exists. The comment explains the architectural purpose.
**ELI5:** A sign on a junction box that says "this controls which wire carries power."
**Best practice:** Keep this kind of architectural comment updated. If you add a new provider, add it to the commented list below so future developers know their options.

---

### Line 2 — The active import
```python
from .openai_api import map_segments
```
**What it does:** Pulls the `map_segments` function from `openai_api.py` in the same directory and makes it accessible as `map_segments` from this module.
**Why:** The relative import (`.openai_api`) keeps the package portable. Any file that does `from adapters.llm import map_segments` gets the OpenAI implementation, without knowing which file it actually came from.
**ELI5:** You label your power strip outlet "LLM." Whether you plug in a US adapter or a UK adapter, the label stays the same. Only the plug changes.
**Best practice:** This is the adapter pattern. The consumer (`nodes.py`) never needs to change when you switch providers — only this file changes.

---

### Lines 3–4 — Commented-out alternatives
```python
# from .azure_openai import map_segments
# from .vertex_ai import map_segments
```
**What it does:** Documents two additional LLM providers that could be activated with a one-line swap. Currently inactive.
**Why:** Enterprise healthcare deployments often prefer Azure OpenAI because it can be hosted in a HIPAA-compliant Azure tenant with a Business Associate Agreement already in place. Vertex AI similarly for Google Cloud deployments.
**ELI5:** These are the spare keys hanging next to the front door. You don't use them every day, but you know where they are.
**Best practice:** Each alternative would be a separate file (`azure_openai.py`, `vertex_ai.py`) that exports a `map_segments` function with the exact same signature. This is contract-based design — any implementation that matches the contract can be plugged in.

## Common Mistakes
1. **Importing `map_segments` directly from `openai_api.py` in other files.** If `nodes.py` did `from adapters.openai_api import map_segments`, switching to Azure would require changing `nodes.py` instead of just `llm.py`. Always import through the adapter.
2. **Activating two imports at once.** If both `from .openai_api import map_segments` and `from .azure_openai import map_segments` are uncommented, Python will silently use whichever was defined last (the Azure one in this ordering). There is no error — just a silent override.
3. **Creating a new provider file that doesn't match the contract.** The `map_segments` function must accept `list[dict]` and return `list[dict]` with `{id, soap_section}` entries. If the new provider returns a different shape, the validation step in the consuming code will silently produce all-UNCLASSIFIED results.

## Key Concepts To Look Up
- The adapter pattern (also called the wrapper pattern)
- Python package `__init__.py` and re-exports
- HIPAA Business Associate Agreements and why cloud provider choice matters
- Azure OpenAI and Vertex AI as alternatives to OpenAI's direct API
- Interface contracts in Python (duck typing)
