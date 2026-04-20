# train.py (confidence_rescorer) — PyTorch Training Loop

## What This File Is For
Trains the confidence re-scorer model using real session data from the audit log. Provider corrections (segments the doctor edited) become low-reliability training examples. Approved sessions with no corrections become high-reliability examples. Run this after accumulating real data.

## How It Fits In The Project
This is a standalone script — run it with `python -m models.confidence_rescorer.train`. It reads from the SQLite database, trains the model defined in `model.py`, and saves the weights to `weights.pt`. The running pipeline loads those weights via `infer.py`.

---

## Line-by-Line Breakdown

### Lines 1–14 — Imports and constants
```python
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
SECTION_IDX = {'S': 0, 'O': 1, 'A': 2, 'P': 3}
WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), 'weights.pt')
```
**What it does:** Imports PyTorch training tools and defines where weights will be saved.
**Why — Dataset and DataLoader:** PyTorch's `Dataset` class defines how to access one sample. `DataLoader` wraps it and handles batching, shuffling, and parallel loading. This split is deliberate — data loading logic and training loop logic are separated.
**ELI5:** `Dataset` is the recipe box (holds individual recipes). `DataLoader` is the person who grabs a handful of recipes at a time and hands them to the chef.
**Best practice:** Always use `DataLoader` over manual batching. It handles edge cases (last batch being smaller), is faster with `num_workers`, and is the universal PyTorch convention.

### Lines 17–45 — SegmentDataset class
```python
class SegmentDataset(Dataset):
    def __init__(self):
        self.samples = []
        self._load_from_db()

    def _load_from_db(self):
        # Approved segments with no edits → label 1.0 (reliable)
        # Edited segments → label 0.3 (less reliable)
```
**What it does:** Defines the training dataset by querying the audit log. Segments approved without edits get label 1.0. Segments the provider corrected get label 0.3.
**Why label 0.3, not 0.0:** An edited segment wasn't completely wrong — the ASR got most of it right. `0.3` (not zero) reflects that it was partially reliable. A completely invented segment would be `0.0`.
**ELI5:** Think of it like a test. A segment the provider didn't touch got 100%. A segment they corrected got 30%. The model learns what "good" looks like vs what "needs checking" looks like.
**Best practice:** Your training labels come from real provider behavior — this is implicit feedback learning. Every time a provider corrects the system, they're labeling a training example.

### Lines 47–54 — __len__ and __getitem__
```python
def __len__(self):
    return len(self.samples)

def __getitem__(self, idx):
    features, label = self.samples[idx]
    return torch.tensor(features, dtype=torch.float32), torch.tensor([label], dtype=torch.float32)
```
**What it does:** These two methods are required by `Dataset`. `__len__` tells the DataLoader how many samples exist. `__getitem__` returns one sample as PyTorch tensors.
**Why `dtype=torch.float32`:** Neural networks work with 32-bit floats. Python lists contain 64-bit floats by default. Explicit dtype avoids silent precision conversion.
**ELI5:** The DataLoader asks "how many items do you have?" and "give me item number 42." These two methods answer those questions.
**Best practice:** Always convert to tensors in `__getitem__`, not in the training loop. It keeps the training loop clean and enables DataLoader parallelism.

### Lines 57–80 — train function
```python
def train(epochs=50, lr=1e-3):
    loader = DataLoader(dataset, batch_size=16, shuffle=True)
    model = ConfidenceRescorer()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.MSELoss()

    model.train()
    for epoch in range(epochs):
        for X, y in loader:
            optimizer.zero_grad()
            pred = model(X)
            loss = criterion(pred, y)
            loss.backward()
            optimizer.step()
```
**What it does:** The complete training loop — the core of PyTorch.
**Why each line:**
- `optimizer.zero_grad()` — clears gradients from the previous batch. PyTorch accumulates gradients by default. Forgetting this is one of the most common PyTorch bugs.
- `pred = model(X)` — forward pass: feed input through the network, get predictions.
- `loss = criterion(pred, y)` — measure how wrong the predictions are.
- `loss.backward()` — backpropagation: compute how much each weight contributed to the loss.
- `optimizer.step()` — update weights in the direction that reduces the loss.
**ELI5:** Show the model a batch of examples. Check how wrong it was. Figure out which parts of the model were most responsible for the errors. Nudge those parts in the right direction. Repeat 50 times.
**Why MSELoss:** Mean Squared Error treats the output as a continuous score, not a class. Since reliability is a continuous value (not just 0 or 1), MSE is appropriate.
**Best practice:** The zero_grad → forward → loss → backward → step sequence is the universal PyTorch training loop. Memorize it.

---

## Common Mistakes
1. Forgetting `optimizer.zero_grad()` — gradients accumulate across batches, making training unstable.
2. Calling `model(X)` after `torch.no_grad()` during training — disables gradient tracking, so `backward()` has nothing to work with.
3. Not calling `model.train()` — Dropout and BatchNorm behave differently in eval mode. Always set `model.train()` before training.

## Key Concepts To Look Up
- PyTorch training loop — the canonical zero_grad → forward → backward → step pattern
- Gradient descent and backpropagation — the math behind `loss.backward()`
- MSE vs BCE loss — when to use each
- Learning rate (lr) — what happens when it's too high or too low
- Implicit feedback learning — using user corrections as training labels
