# Contract: live-session page

**Feature**: 004-live-session-recording

Controls (top to bottom):

- Exercise selectbox: display names from `analyze.load_config()` (keys behind the scenes).
- Target reps number input (1–100, default from the config target).
- Camera selectbox: Default / Front Camera / Back Camera (unchanged).
- The WebRTC stream with its own Start/Stop.
- While playing: "Switch exercise" applies the selectbox choice to the running session
  (button), "Reset reps" button, "Save Screenshot" button, a caption
  `Recording session <id> for <patient>`.
- Not playing and a session id in state: a summary block (`Session <id> — <n> reps, avg form
  <x>/100, avg ROM <y>°, <d> s`, status shown when interrupted) and an "Open in Sessions"
  button that switches to the Sessions page with that session selected.
- No "Save Session" control.

States:

| State | What the PT sees |
|-------|------------------|
| idle | controls, stream placeholder, last summary if any |
| loading | stream started, model loading, caption "Starting…" |
| playing | annotated stream with the engine panel; caption with session id and patient |
| stopped | summary block from the record and the Sessions link |
| error | `st.error` with the recorder's message; stream keeps running |
