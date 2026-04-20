# infer.py (role_classifier) — TensorFlow/Keras Runtime Inference

## What This File Is For
Loads the trained Keras role classifier and exposes a `classify()` function. Given six acoustic features for a segment, returns 'DOCTOR' or 'PATIENT'. Called by `role_classify_node` to cross-check pyannote's diarization labels.

## How It Fits In The Project
`role_classify_node` in `nodes.py` calls `classify()` for each segment. If the classification disagrees with pyannote's label, the segment gets a `role_flag` and shows a warning in the review UI for the provider to resolve.

---

## Line-by-Line Breakdown

### Lines 1–7 — Imports and lazy model
```python
import numpy as np
import os

WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), 'weights.keras')
_model = None
```
**What it does:** Sets up the weights path and a None placeholder for lazy loading.
**Why numpy:** Keras expects numpy arrays as input, not Python lists. `np.array([[...]])` creates the right shape and dtype.
**Best practice:** Same lazy singleton pattern as the PyTorch infer.py. Consistent patterns across both ML frameworks make the codebase easier to reason about.

### Lines 9–17 — _load function
```python
def _load():
    global _model
    import tensorflow as tf
    if os.path.exists(WEIGHTS_PATH):
        _model = tf.keras.models.load_model(WEIGHTS_PATH)
    else:
        from .model import build_model
        _model = build_model()
```
**What it does:** Loads a saved model or creates an untrained one if no weights exist.
**Why import TF inside the function:** TensorFlow takes several seconds to import. By importing inside `_load()` rather than at module level, the Python pipeline starts faster — TF only loads when the role classifier is first called.
**Why `tf.keras.models.load_model` vs `load_state_dict`:** Keras saves the full model (architecture + weights) so loading is one call. PyTorch saves only weights, so you must instantiate the architecture first, then load weights.
**ELI5:** Keras is like saving a fully assembled LEGO set in a box. PyTorch is like saving just the instruction manual — you have to build the set first, then follow the instructions to set it up the way it was.
**Best practice:** Deferred imports (inside functions) are a valid performance optimization for heavy libraries. Use them when the import time is significant and the module isn't always needed.

### Lines 20–33 — classify function
```python
def classify(pitch_mean, pitch_var, rate_wps, pause_ratio, avg_word_len, duration_s) -> str:
    global _model
    if _model is None:
        _load()

    features = np.array([[pitch_mean, pitch_var, rate_wps, pause_ratio, avg_word_len, duration_s]])
    prob = _model.predict(features, verbose=0)[0][0]
    return 'DOCTOR' if prob >= 0.5 else 'PATIENT'
```
**What it does:** Runs one prediction. Returns 'DOCTOR' if probability ≥ 0.5, else 'PATIENT'.
**Why `np.array([[...]])`:** The `[[...]]` creates a 2D array of shape `(1, 6)` — one sample, six features. Keras expects batch input even for single predictions.
**Why `[0][0]`:** `model.predict()` returns shape `(1, 1)` — a batch of one result, each result being one value. `[0]` gets the first (only) sample, `[0]` gets the first (only) output value.
**Why `verbose=0`:** Suppresses Keras's progress bar output. Without it, every call prints "1/1 ━━━━━━━━━━━━ 0s" to the console — 40+ times per session.
**Why 0.5 threshold:** The model outputs a probability. 0.5 is the natural midpoint for binary classification. Adjust this if you find the model is biased toward one class.
**ELI5:** Feed six numbers into the brain, get back one number between 0 and 1. If it's above 0.5, say "Doctor." If not, say "Patient."
**Best practice:** Use `verbose=0` for all production `predict()` calls. Log the raw probability alongside the classification when debugging — `prob=0.51` and `prob=0.99` are both "DOCTOR" but very different confidence levels.

---

## Comparing PyTorch vs Keras Inference

| | PyTorch (confidence_rescorer) | Keras (role_classifier) |
|--|--|--|
| Input | `torch.tensor([[...]])` | `np.array([[...]])` |
| Inference call | `model(x)` | `model.predict(features)` |
| Disable gradients | `torch.no_grad()` | Not needed (Keras handles it) |
| Extract scalar | `.item()` | `[0][0]` |
| Eval mode | `model.eval()` required | Handled automatically by `predict()` |

---

## Common Mistakes
1. Forgetting `verbose=0` in `predict()` — spams the terminal with progress bars.
2. Passing a 1D array `[f1, f2, ...]` instead of 2D `[[f1, f2, ...]]` — Keras raises a shape error.
3. Not logging the raw probability — "DOCTOR" tells you the label, not the confidence. A 0.51 DOCTOR and 0.99 DOCTOR are very different.

## Key Concepts To Look Up
- `model.predict()` vs `model(x)` in Keras — when to use each
- Numpy array shapes and dimensions — (6,) vs (1,6)
- Classification threshold tuning — when to adjust the 0.5 cutoff
- Keras `verbose` parameter
