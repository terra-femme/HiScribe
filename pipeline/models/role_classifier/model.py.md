# model.py (role_classifier) — TensorFlow/Keras DOCTOR vs PATIENT Classifier

## What This File Is For
This file defines a Keras neural network that looks at acoustic features of a speech segment and predicts whether the speaker is a DOCTOR or a PATIENT. It cross-checks pyannote's diarization labels — if the two disagree, the segment gets flagged for provider review.

## How It Fits In The Project
`train.py` calls `build_model()` to create and train the model. `infer.py` loads the saved model and calls `model.predict()` at runtime. `role_classify_node` in `nodes.py` calls `infer.py`.

---

## Line-by-Line Breakdown

### Line 1 — Import
```python
import tensorflow as tf
```
**What it does:** Imports TensorFlow, which includes Keras as `tf.keras`.
**Why:** Keras is TensorFlow's high-level API. It's more concise than raw TensorFlow and easier to read. `tf.keras` is the standard way to access it since TF 2.0.
**ELI5:** TensorFlow is the whole kitchen. Keras is the easy-to-use stove with preset burner controls.
**Best practice:** Always use `tf.keras` rather than importing Keras standalone. The standalone `keras` package and `tf.keras` can conflict in older environments.

### Lines 4–20 — build_model function
```python
def build_model() -> tf.keras.Model:
    """
    Input:  [pitch_mean, pitch_variance, speaking_rate_wps,
             pause_ratio, avg_word_length, segment_duration_s]
    Output: probability of DOCTOR [0=PATIENT, 1=DOCTOR]
    """
    inputs = tf.keras.Input(shape=(6,), name='voice_features')
    x = tf.keras.layers.Dense(32, activation='relu')(inputs)
    x = tf.keras.layers.Dropout(0.2)(x)
    x = tf.keras.layers.Dense(16, activation='relu')(x)
    output = tf.keras.layers.Dense(1, activation='sigmoid', name='role')(x)
    model = tf.keras.Model(inputs=inputs, outputs=output)
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
    return model
```

**`tf.keras.Input(shape=(6,))`**
**What it does:** Defines the input layer — 6 features per sample.
**Why:** The 6 features are acoustic properties extracted from the audio segment. Doctors and patients have measurably different speech patterns in clinical settings (doctors speak faster, use longer words, pause less). The network learns which combinations of these features predict the role.
**ELI5:** The model's "eyes" — it expects to see exactly 6 numbers for every segment it classifies.
**Best practice:** Always name your input layer. It makes the model easier to debug and inspect.

**`Dense(32, activation='relu')`**
**What it does:** A fully-connected layer with 32 neurons and ReLU activation.
**Why:** Same reasoning as the PyTorch model — linear layers learn patterns, ReLU adds non-linearity. The Keras syntax is more concise: you pass `activation` as a parameter instead of adding a separate layer.
**ELI5:** 32 little detectors, each looking for a different combination of the 6 input features.
**Best practice:** Keras's functional API (`layer(previous_layer)`) is more flexible than Sequential for complex models. Use it even for simple models to build the habit.

**`Dropout(0.2)`**
**What it does:** During training, randomly sets 20% of neurons to zero on each forward pass.
**Why:** Dropout is a regularization technique that prevents overfitting. Overfitting means the model memorizes the training data but fails on new data. By randomly disabling neurons during training, it forces the network to learn redundant representations — multiple paths to the right answer.
**ELI5:** Imagine practicing a sports play where any player might randomly sit out. The team gets better at the play even when someone is missing, rather than depending on one star player.
**Best practice:** Dropout is only applied during training, not inference. Keras handles this automatically with `model.predict()` (inference mode) vs `model.fit()` (training mode). In PyTorch you have to call `model.eval()` manually.

**`model.compile(...)`**
**What it does:** Configures the model for training — optimizer, loss function, and metrics.
- `optimizer='adam'` — Adam is the standard optimizer for most neural networks. It adapts the learning rate per parameter automatically.
- `loss='binary_crossentropy'` — the standard loss for binary classification (two classes: DOCTOR/PATIENT). It measures how wrong the model's probability estimate is.
- `metrics=['accuracy']` — tracks what % of predictions are correct during training.
**ELI5:** You tell the coach (optimizer) how to improve (loss function) and how to track progress (accuracy).
**Best practice:** Use `binary_crossentropy` for two-class problems with a sigmoid output. Use `categorical_crossentropy` for multi-class problems with a softmax output. Getting this wrong produces silently bad training.

---

## PyTorch vs TensorFlow/Keras — Why Both Are Used Here

| | PyTorch (confidence rescorer) | TensorFlow/Keras (role classifier) |
|--|--|--|
| Style | More explicit, more control | More concise, higher level |
| Training loop | Written manually | `model.fit()` handles it |
| When to use | Research, custom architectures | Production, standard architectures |
| This project | Learning PyTorch fundamentals | Learning Keras API |

Both are included intentionally as a learning exercise — you're building familiarity with both ecosystems.

---

## Common Mistakes
1. Forgetting to call `model.compile()` before `model.fit()` — raises a cryptic error about the model not being compiled.
2. Using `Dropout` during inference — always call `model.predict()` not `model(x, training=True)` at inference time.
3. Confusing `binary_crossentropy` and `categorical_crossentropy` — binary is for 1 output neuron (sigmoid), categorical is for N output neurons (softmax).

## Key Concepts To Look Up
- Keras functional API vs Sequential API
- Dropout regularization — overfitting vs underfitting
- Adam optimizer — how adaptive learning rates work
- Binary cross-entropy loss — the math behind it
- Why acoustic features predict speaker role in clinical settings
