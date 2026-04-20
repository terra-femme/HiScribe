# model.py (confidence_rescorer) — PyTorch Neural Network Definition

## What This File Is For
This file defines the architecture of a small feedforward neural network that scores how reliable a transcript segment is. Given features about a segment (ASR confidence, length, which SOAP section), it outputs a number between 0 and 1. Below 0.6 means the segment should be flagged for the provider to review.

## How It Fits In The Project
`infer.py` loads this model class and runs it at inference time. `train.py` instantiates this class and trains it. `score_node` in `nodes.py` calls `infer.py`, which uses this model.

---

## Line-by-Line Breakdown

### Lines 1–2 — Imports
```python
import torch
import torch.nn as nn
```
**What it does:** Imports PyTorch and its neural network module.
**Why:** `torch` is the core library — tensors, math operations, GPU support. `torch.nn` contains the building blocks for neural networks: layers, activation functions, loss functions.
**ELI5:** `torch` is the construction company. `torch.nn` is the specific toolkit for building neural network buildings.
**Best practice:** Always import `torch.nn as nn` — it's the universal convention in PyTorch code and makes your code readable to anyone who knows PyTorch.

### Lines 5–7 — Class definition
```python
class ConfidenceRescorer(nn.Module):
    """
    Input:  [asr_confidence, segment_token_count, soap_S, soap_O, soap_A, soap_P]
    Output: reliability score [0, 1]
    """
```
**What it does:** Defines the model as a subclass of `nn.Module`.
**Why:** Every PyTorch model must inherit from `nn.Module`. This gives it automatic parameter tracking (so the optimizer knows what to update), the `.to(device)` method (to move to GPU), `.train()` and `.eval()` modes, and `.state_dict()` / `.load_state_dict()` for saving and loading.
**ELI5:** `nn.Module` is like a standard electrical outlet. Your device (the model) must fit this outlet shape. In return, it gets all the features of the electrical system for free.
**Best practice:** Always document the input shape and output shape in the docstring. Neural networks are black boxes — the docstring is the contract.

### Lines 9–17 — Constructor: define layers
```python
def __init__(self):
    super().__init__()
    self.net = nn.Sequential(
        nn.Linear(6, 32), nn.ReLU(),
        nn.Linear(32, 16), nn.ReLU(),
        nn.Linear(16, 1), nn.Sigmoid()
    )
```
**What it does:** Defines the network architecture as a sequence of layers.
**Why each layer:**
- `nn.Linear(6, 32)` — takes 6 input features, outputs 32 values. This is where the network learns patterns.
- `nn.ReLU()` — activation function. Sets all negative values to 0. Without this, stacking linear layers would just be one big linear layer (useless). ReLU adds non-linearity — the ability to learn complex patterns.
- `nn.Linear(32, 16)` — compresses 32 values to 16. The network learns which of the 32 intermediate features matter.
- `nn.Linear(16, 1)` — compresses to a single score.
- `nn.Sigmoid()` — squashes any value to [0, 1]. This is what makes the output a "score" rather than an arbitrary number.
**ELI5:** Imagine a conveyor belt with workers at each station. Station 1 takes 6 ingredients and mixes them into 32 combinations. Station 2 (ReLU) throws away anything negative. Station 3 picks the 16 most interesting combinations. Station 4 distills those into 1 score. The final station makes sure the score is between 0 and 1.
**Best practice:** `super().__init__()` must be the first line of `__init__`. It initializes the parent `nn.Module`, which sets up internal PyTorch bookkeeping. Forgetting it causes cryptic errors.

### Lines 19–21 — Forward pass
```python
def forward(self, x: torch.Tensor) -> torch.Tensor:
    return self.net(x)
```
**What it does:** Defines what happens when you "run" the model on input data.
**Why:** In PyTorch, you define `forward()` and PyTorch automatically handles `backward()` (gradient computation for training). You never call `forward()` directly — you call the model like a function: `model(x)`, which internally calls `forward(x)`.
**ELI5:** `forward` is the recipe. When you call `model(x)`, PyTorch follows the recipe. When training, PyTorch also automatically figures out how to improve the recipe (backpropagation).
**Best practice:** Keep `forward()` clean and readable. If your forward pass is complex (branches, loops), consider breaking it into helper methods.

---

## Common Mistakes
1. Forgetting `super().__init__()` — causes confusing `AttributeError` when PyTorch tries to register parameters.
2. Using `Sigmoid` as a hidden layer activation — Sigmoid in hidden layers causes the "vanishing gradient" problem during training. Use `ReLU` for hidden layers, `Sigmoid` only for the final output when you need [0,1].
3. Calling `model.forward(x)` directly — always call `model(x)`. The `__call__` method does important bookkeeping (hooks, grad tracking) that `forward()` bypasses.

## Key Concepts To Look Up
- `nn.Module` — PyTorch's base class for all models
- Linear layers — what a weight matrix does mathematically
- ReLU activation function — why non-linearity matters
- Sigmoid function — how it maps any number to [0, 1]
- `nn.Sequential` — composing layers in order
- Vanishing gradients — why ReLU replaced Sigmoid in hidden layers
