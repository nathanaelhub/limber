# Contract: LiveSession and LiveVideoProcessor

**Feature**: 004-live-session-recording

## src/live_session.py

```python
class LiveSession:
    def __init__(self, store: SessionStore, patient_id: str | None, exercise_key: str, target_reps: int | None,
                 source_ref: str, infer: Callable[[np.ndarray], np.ndarray | None],
                 fps: float = 30.0, config_path: str = "config.yaml", imgsz: int = 320,
                 form_analyzer_factory=None, draw: bool = True): ...
    def start(self) -> int                     # opens the session and first set; returns session_id; idempotent
    def process(self, frame: np.ndarray, frame_num: int | None = None) -> np.ndarray
        # infer → angle → tracker.update → analyzer → recorder.observe → annotated frame (skeleton when
        # the infer result carries a plotted image is not required; the adapter draws angle + panel)
    def switch(self, exercise_key: str) -> None      # like the CLI 'n' key: interrupted partial, recorder.switch, new tracker/analyzer
    def reset(self) -> None                          # like the CLI 'r' key: interrupted partial, recorder.reset, new tracker
    def end(self) -> Session | None                  # finalize tracker, recorder.end; idempotent
    @property session_id, metrics (last dict), last_frame, last_assessment, exercise_name, ended
```

Guarantees:

- Uses only `ExerciseTracker`, `FormAnalyzer`, `get_angle_from_keypoints`,
  `draw_angle_visualization`, `draw_metrics_panel`, `load_config` from the engine, and
  `SessionRecorder` / `SessionStore` from the record. Never reads tracker internals beyond the
  public outputs the recorder already uses; the interrupted-partial call at switch/reset uses
  the same private method the command-line loop calls (`tracker._record_partial_rep`).
- `target_reps`, when given, replaces the config target on the set opened at `start()` and on
  sets opened by `switch()` after it was set.
- Every public method takes the internal lock; `process()` returns the raw frame unchanged when
  called before `start()` or after `end()`.
- On store failure the recorder's degraded mode applies; `end()` re-raises the first error and
  the processor exposes it as `error`.

## interfaces/app.py: LiveVideoProcessor(VideoProcessorBase)

```python
patient_id: str | None; exercise_key: str; target_reps: int; camera_label: str; db_path: Path
live: LiveSession | None; session_id: int | None; last_frame; error: str | None
pending_switch: str | None; pending_reset: bool
def request_switch(self, exercise_key) ; def request_reset(self)
def recv(self, frame) -> av.VideoFrame   # creates LiveSession on first frame; applies pending requests; process
def on_ended(self)                        # live.end() under the lock; safe if never started
```

## Screenshot

`save_screenshot(frame, patient_id, out_dir=None, now=None) -> Path` writes
`<patient_id>_<YYYYMMDD_HHMMSS>.png` under `exports/` (or `out_dir`) and returns the path.
