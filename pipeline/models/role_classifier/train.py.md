# train.py (role_classifier) — TensorFlow/Keras Training Script

## What This File Is For
Trains the DOCTOR vs PATIENT role classifier. Uses synthetic training data (generated with numpy) on first run, then improves with real data from provider corrections as the system accumulates approved sessions.

## How It Fits In The Project
Run with `python -m models.role_classifier.train`. Reads corrections from `audit_log`, trains the Keras model from `model.py`, and saves weights to `weights.keras`. `infer.py` loads those weights at runtime.

---

## Line-by-Line Breakdown

### Lines 1–10 — Imports
```python
import numpy as np
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from models.role_classifier.model import build_model
from db.sqlite import _conn
```
**What it does:** Imports numpy for matrix operations, and sets up the Python path so relative imports work when running this as a script.
**Why `sys.path.insert`:** When running `python -m models.role_classifier.train` from the `pipeline/` directory, Python doesn't automatically know about the project root. `sys.path.insert(0, ...)` adds the `pipeline/` directory to the module search path, making `from db.sqlite import _conn` work.
**ELI5:** Python needs to know where to look for files when you say `import something`. This line says "also look in this folder."
**Best practice:** This is a common pattern for standalone scripts in packages. An alternative is always running scripts with `python -m` from the correct directory. Document which approach your project uses.

### Lines 21–57 — load_training_data with synthetic fallback
```python
def load_training_data():
    # Try real data from audit_log first
    # Fall back to synthetic data if none available

    # DOCTOR: higher speaking rate, longer words, lower pause ratio
    doctor_features = np.random.normal(
        loc=[140, 15, 3.2, 0.1, 6.5, 8.0],
        scale=[20, 5, 0.5, 0.05, 1.0, 2.0],
        size=(200, 6)
    )
    # PATIENT: lower speaking rate, shorter words, higher pause ratio
    patient_features = np.random.normal(...)
```
**What it does:** Generates 400 synthetic training samples (200 doctor, 200 patient) using normally distributed random values centered on realistic acoustic feature values.
**Why synthetic first:** You can't wait for 1000 real sessions to train a model. Synthetic data bootstraps the model with reasonable behavior from day one. Real data improves it incrementally.
**Why `np.random.normal(loc=..., scale=...)`:** `loc` is the mean (average value), `scale` is the standard deviation (how much variation). Doctors' pitch means center around 140Hz with ±20Hz variation — realistic for the population.
**ELI5:** Imagine you've never met a doctor or patient but someone described the typical acoustic differences. You invent 200 imaginary doctors and 200 imaginary patients based on that description. Not perfect, but enough to start learning.
**Best practice:** Always document the biological/empirical basis for synthetic feature values. Don't pick numbers arbitrarily — look up real studies on clinical speech patterns.

### Lines 59–70 — train function
```python
def train(epochs=30):
    X, y = load_training_data()
    model = build_model()
    model.fit(
        X, y,
        epochs=epochs,
        batch_size=32,
        validation_split=0.2,
        verbose=1
    )
    model.save(WEIGHTS_PATH)
```
**What it does:** Loads data, builds the model, trains it, and saves the weights.
**Why this is simpler than PyTorch:** Keras's `model.fit()` replaces the entire manual training loop from `confidence_rescorer/train.py`. It handles the batching, gradient computation, optimizer step, and metric tracking automatically. The explicit PyTorch loop is better for learning; Keras is better for speed.
**Why `validation_split=0.2`:** Holds out 20% of data for validation — measures performance on unseen data during training. If training accuracy is high but validation accuracy is low, the model is overfitting.
**Why `model.save()` vs `torch.save()`:** Keras `save()` saves the entire model (architecture + weights) in one file. PyTorch `save(state_dict)` saves only the weights. PyTorch's approach is more portable; Keras's is more convenient.
**ELI5:** You explain the differences to a student (feed data), quiz them repeatedly (epochs), check their work on problems they haven't seen (validation), and file their diploma (save weights).
**Best practice:** Always use `validation_split` during training. Never evaluate a model only on its training data — that tells you nothing about real performance.

---

## Common Mistakes
1. Using the same data for training and validation — the model looks perfect but fails on new data.
2. Picking synthetic feature values without researching realistic ranges — a model trained on wrong distributions will perform poorly.
3. Forgetting to retrain when enough real data accumulates — synthetic bootstrapping is temporary.

## Key Concepts To Look Up
- `model.fit()` in Keras — what it handles under the hood
- `validation_split` — training vs validation vs test sets
- Overfitting — why validation accuracy matters
- `np.random.normal` — normal distribution, mean and standard deviation
- Synthetic data bootstrapping — pros and cons
