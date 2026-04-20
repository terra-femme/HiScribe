# infer.py (confidence_rescorer) — PyTorch Runtime Inference

## What This File Is For
Loads the trained model weights and exposes a single `score()` function that the pipeline calls at runtime. Given a segment's features, returns a reliability score between 0 and 1.

## How It Fits In The Project
`score_node` in `nodes.py` calls `score()` from this file for every segment after SOAP mapping. Segments scoring below 0.6 get a `confidence_flag` that shows as a yellow warning in the review UI.

---

## Line-by-Line Breakdown

### Lines 1–6 — Imports and paths
```python
import torch
import os
from .model import ConfidenceRescorer

WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), 'weights.pt')
_model = None
```
**What it does:** Sets up the path to the weights file and a module-level variable to hold the loaded model.
**Why `_model = None`:** Lazy loading — the model isn't loaded until the first call to `score()`. This keeps server startup fast. The `_` prefix signals it's private to this module.
**ELI5:** The model is a heavy book. You don't carry it with you all day — you only pick it up the first time someone asks you a question from it.
**Best practice:** Module-level singletons with lazy initialization are the standard pattern for ML models in production. Loading a model takes seconds; you only want to do it once.

### Lines 9–16 — _load function
```python
def _load():
    global _model
    _model = ConfidenceRescorer()
    if os.path.exists(WEIGHTS_PATH):
        _model.load_state_dict(torch.load(WEIGHTS_PATH, map_location='cpu'))
        print('[confidence_rescorer] Weights loaded')
    else:
        print('[confidence_rescorer] No weights found — using untrained model')
    _model.eval()
```
**What it does:** Creates the model, loads saved weights if they exist, sets to eval mode.
**Why `map_location='cpu'`:** If the model was trained on a GPU but the server runs on CPU, `map_location='cpu'` ensures the weights load correctly regardless of where they were saved.
**Why `model.eval()`:** Switches the model from training mode to inference mode. In this model there's no Dropout, so it doesn't change behavior — but it's always correct practice to call `eval()` before inference.
**ELI5:** Load the brain (model architecture), load the memories (trained weights), and put it in "answer questions" mode (eval) rather than "learning" mode.
**Best practice:** Always call `model.eval()` before inference. Always use `map_location='cpu'` when loading weights in a mixed GPU/CPU environment.

### Lines 19–32 — score function
```python
def score(asr_confidence: float, token_count: int, soap_section: str) -> float:
    global _model
    if _model is None:
        _load()

    onehot = [0.0] * 4
    onehot[SECTION_IDX.get(soap_section or 'S', 0)] = 1.0
    x = torch.tensor([[asr_confidence, float(token_count)] + onehot], dtype=torch.float32)

    with torch.no_grad():
        return _model(x).item()
```
**What it does:** Builds the input tensor and runs one forward pass.
**Why one-hot encoding:** The SOAP section is a category (S/O/A/P), not a number. You can't say S=1, O=2, A=3, P=4 because that implies O is "twice S," which is meaningless. One-hot encoding gives each category its own dimension: S=[1,0,0,0], O=[0,1,0,0], etc.
**Why `torch.no_grad()`:** During inference, you don't need to compute gradients (no training happening). `no_grad()` skips gradient computation, using less memory and running faster.
**Why `.item()`:** `_model(x)` returns a tensor of shape `[1,1]`. `.item()` extracts the single Python float value from it.
**ELI5:** Prepare the question (build the tensor), ask the model (forward pass), and extract just the number from the answer (`.item()`).
**Best practice:** Always wrap inference in `torch.no_grad()`. Forgetting it doesn't break anything, but wastes memory and time computing gradients nobody will use.

---

## Common Mistakes
1. Forgetting `torch.no_grad()` during inference — wastes memory; can cause OOM errors on large batches.
2. Calling `_load()` every time `score()` is called — makes inference 100x slower due to disk I/O.
3. Not calling `model.eval()` — models with Dropout will randomly zero out neurons during inference, giving inconsistent results.

## Key Concepts To Look Up
- `torch.no_grad()` — gradient context manager
- `model.eval()` vs `model.train()` — the two modes and when to use each
- One-hot encoding — how to represent categorical data numerically
- `.item()` — extracting a scalar from a PyTorch tensor
- Lazy loading pattern for ML models
