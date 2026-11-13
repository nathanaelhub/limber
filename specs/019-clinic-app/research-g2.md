# Research: gate G2 (= 020 G5), browser pose against the clinic model

**Date**: 13 November 2026. **Question**: is MoveNet Lightning in the therapist's browser good enough for the hosted
demo's video analysis, and how should its sessions sit beside YOLO sessions?

## Method
- Clips: the three Ultralytics demo clips, `Squats`, `Pushups` and `Legextension` (issue #23), from the
  `ultralytics/assets` v0.0.0 release. No ground truth beyond hand-counted reps: 4, 4 and 3.
- **MoveNet points:** headless Chrome plays each clip at quarter speed and runs MoveNet Lightning on the frame shown
  every 1/15 s of clip time, exactly as `session.js` does (no flip, no smoothing).
  - A first attempt that seeked a paused video read the same frame over and over (the knee barely moved, 0 reps);
    it was caught by checking the points against YOLO's before trusting the counts, and replaced.
- **YOLO points:** YOLO11m-pose on the same 1/15 s frames, the most confident person.
- **Both** go through the real engine (`LiveSession`, fps 15, a 1/15 s clock), the path the hosted video analysis
  will use, so the pose model is the only difference.
- Reproduce: `python scripts/compare_pose.py` (points in `tests/fixtures/pose/`); `tests/test_pose_compare.py` pins
  the results.

## Results

| Clip | Exercise | Model | Reps (hand count) | Avg ROM | Avg form | Partial reps | Form events |
|---|---|---|---|---|---|---|---|
| Squats | squat | YOLO11m | 4 (4) | 117.5° | 66.2 | 0 | 2 |
| Squats | squat | MoveNet | 4 (4) | 109.4° | 67.9 | 0 | 2 |
| Push-ups | pushup | YOLO11m | 4 (4) | 82.6° | 65.9 | 0 | 2 |
| Push-ups | pushup_right | YOLO11m | 4 (4) | 80.5° | 66.0 | 0 | 2 |
| Push-ups | pushup | MoveNet | 4 (4) | 96.5° | 67.2 | 0 | 1 |
| Push-ups | pushup_right | MoveNet | 4 (4) | 101.7° | 67.8 | 0 | 1 |
| Leg extension | knee_extension | YOLO11m | 1 (3) | 63.5° | 65.5 | 1 | 2 |
| Leg extension | knee_extension_right | YOLO11m | 2 (3) | 77.0° | 72.7 | 1 | 2 |
| Leg extension | knee_extension | MoveNet | 0 (3) | — | — | 3 | 0 |
| Leg extension | knee_extension_right | MoveNet | 0 (3) | — | — | 3 | 0 |

## Findings
1. **Rep counts and form scores agree** on the side-on clips (squats, push-ups): 4 of 4 with both models, form
   within 2 points.
2. **Range of motion does not agree**: MoveNet reads 8° less on squats and 14–21° more on push-ups, the same pattern
   007 research D2 found. Without ground truth this is disagreement, not error.
3. **The leg-extension clip defeats both models** (issue #23): filmed from the front at an angle, the machine covers
   the knees and the legs overlap. YOLO counts 1–2 of 3, MoveNet 0 full reps and 3 partial ones. This is a camera-
   angle limit, not a browser-pose limit.
4. Issue #24 is real for both models: the side measured changes push-up range of motion by 2° (YOLO) and 5° (MoveNet).

## Recommendation (for the owner's decision)
- **Use MoveNet for hosted video analysis.** It counts and scores like the clinic model where the camera can see.
- **Keep YOLO for local video analysis**, where it can run, so local results stay comparable with past ones.
- **Keep browser-pose sessions apart in trends**, as home and clinic already are (007 FR-020): a session whose
  `pose_source` is `browser` gets its own measurement origin, so its range of motion is never compared with YOLO's.
- **Tell the therapist when a clip can't be measured well** (issue #23's second acceptance option): when a set has
  more partial reps than full ones, the result says the camera angle may have hidden the movement, rather than
  reporting the count as fact. For both models.
