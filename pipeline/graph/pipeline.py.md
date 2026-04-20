# pipeline.py — Assembles the six processing nodes into a runnable LangGraph state machine

## What This File Is For
This file wires the six node functions from `nodes.py` into a directed graph and exposes a single `run_pipeline()` function that starts the whole process. It is the blueprint of the assembly line: it describes the order in which steps happen but does not contain any logic itself. Think of it as the circuit board that connects all the components.

## How It Fits In The Project
`pipeline.py` is imported by `server.py`, which calls `run_pipeline(session_id)` when a POST request arrives at `/pipeline/run`. This file imports all six nodes from `nodes.py` and uses LangGraph's `StateGraph` to build the graph at module load time. The compiled graph (`_app`) is reused for every request.

## Line-by-Line Breakdown

### Lines 1–10 — Imports
```python
from langgraph.graph import StateGraph
from .nodes import (
    ScribeState,
    finalize_node,
    diarize_node,
    role_classify_node,
    map_node,
    score_node,
    package_node
)
```
**What it does:** Imports `StateGraph` from the LangGraph library and all six node functions (plus the `ScribeState` type) from the sibling `nodes.py` file. The `.nodes` syntax (with a leading dot) means "from the `nodes` module in the same package as this file."
**Why:** `StateGraph` is the core LangGraph class for building linear or branching workflows. Importing all nodes here rather than putting logic here keeps each file focused on one responsibility.
**ELI5:** This is like a stage manager calling in all the actors from their dressing rooms before the show. The stage manager doesn't perform — they just know everyone's name and when they go on.
**Best practice:** Relative imports (`.nodes`) are preferred within a package because they make the package self-contained and easier to move or rename. Absolute imports (`from graph.nodes import ...`) depend on the Python path being set up correctly.

---

### Lines 13–20 — Building the graph
```python
_graph = StateGraph(ScribeState)

_graph.add_node('finalize',      finalize_node)
_graph.add_node('diarize',       diarize_node)
_graph.add_node('role_classify', role_classify_node)
_graph.add_node('map',           map_node)
_graph.add_node('score',         score_node)
_graph.add_node('package',       package_node)
```
**What it does:** Creates a new `StateGraph` typed to `ScribeState`, then registers each of the six nodes under a string name.
**Why:** LangGraph uses a graph (nodes + edges) to represent a workflow. Each node is registered with a name that will later be used to define edges between them. The `ScribeState` type tells LangGraph what the shared state object looks like.
**ELI5:** Imagine building a flowchart. This code is drawing each box on the chart and writing a label inside it. The arrows between the boxes come next.
**Best practice:** The underscore prefix on `_graph` and `_app` signals that these are private module-level variables not intended to be imported by other modules. Only `run_pipeline` is the public API.

---

### Lines 22–28 — Defining edges and entry/exit points
```python
_graph.set_entry_point('finalize')
_graph.add_edge('finalize',      'diarize')
_graph.add_edge('diarize',       'role_classify')
_graph.add_edge('role_classify', 'map')
_graph.add_edge('map',           'score')
_graph.add_edge('score',         'package')
_graph.set_finish_point('package')
```
**What it does:** Sets `finalize` as the first node to run, defines the linear chain of directed edges connecting each node to the next, and marks `package` as the terminal node where the graph stops.
**Why:** LangGraph supports branching graphs (where a condition determines which node runs next), but this pipeline is intentionally linear — each step always leads to the next. `set_entry_point` and `set_finish_point` are required to tell LangGraph where execution begins and ends.
**ELI5:** These are the arrows on the flowchart. "After finalize, go to diarize. After diarize, go to role_classify." And so on until the last box.
**Best practice:** Even though this graph is linear, LangGraph supports conditional edges via `add_conditional_edges`. If you later need to branch (e.g., skip diarization if no audio exists at the graph level rather than inside the node), that is the tool to reach for.

---

### Line 30 — Compiling the graph
```python
_app = _graph.compile()
```
**What it does:** Finalizes the graph definition and returns a runnable object. After this line, no more nodes or edges can be added. `_app` is what you actually call to execute the pipeline.
**Why:** LangGraph's two-step pattern (build, then compile) is deliberate. `compile()` validates the graph (checks for unreachable nodes, missing entry points, etc.) and optimizes it for execution. This happens once at module load time, not on every request.
**ELI5:** You can think of building the graph as writing a recipe, and `compile()` as printing it out and laminating it. After lamination, you can use the recipe repeatedly without changing it.
**Best practice:** Compiling at module load time rather than inside `run_pipeline()` is correct — you pay the compile cost once, not on every API call. This is a common performance pattern in Python web services.

---

### Lines 33–45 — The public run_pipeline function
```python
async def run_pipeline(session_id: str) -> dict:
    print(f'[pipeline] Starting for session {session_id}')
    initial_state: ScribeState = {
        'session_id': session_id,
        'segments': [],
        'role_flags': [],
        'mapped_segments': [],
        'scored_segments': [],
        'review_payload': {}
    }
    result = _app.invoke(initial_state)
    print(f'[pipeline] Complete for session {session_id}')
    return result['review_payload']
```
**What it does:** The only public function in this file. Creates an empty initial state with just the `session_id` filled in, invokes the compiled graph with that state, and returns just the `review_payload` from the final state.
**Why:** The initial state must include all keys defined in `ScribeState` — even empty ones — so that every node can safely read any key without a `KeyError`. The pipeline populates these fields progressively as it runs.
**ELI5:** This is like handing a blank intake form to the first worker. Each worker fills in their section and passes it to the next. By the end, every section is filled in.
**Best practice:** The function is marked `async def` because it is called from an `async` FastAPI route. However, `_app.invoke()` is actually synchronous. In a high-throughput system, you would want to use `asyncio.to_thread()` to run the synchronous invoke in a thread pool so it doesn't block the event loop. For the current use case, this is acceptable.

## Common Mistakes
1. **Calling `_graph.add_node` after `compile()`.** Once `compile()` is called, the graph is frozen. Any modifications made after that will either raise an error or be silently ignored. Always finish building before compiling.
2. **Forgetting to include all `ScribeState` keys in the initial state.** If you add a new key to `ScribeState` in `nodes.py` but don't add it to the `initial_state` dict here, nodes that try to read it with `state['new_key']` will raise a `KeyError`. Use `state.get('new_key', default)` in nodes for safety.
3. **Confusing the node name string with the function name.** `_graph.add_node('finalize', finalize_node)` — the first argument is just a label string, the second is the actual function. If you later use `add_edge('finalize', 'diarize')` but accidentally wrote the node as `'finalize_node'`, the edge will reference a non-existent node name.

## Key Concepts To Look Up
- LangGraph `StateGraph` and how it differs from a simple function chain
- Directed acyclic graphs (DAGs) as a model for computation
- Relative vs absolute imports in Python packages
- Python module load time vs call time — when code runs
- `async def` and the asyncio event loop
- LangGraph conditional edges (for when you need branching logic)
