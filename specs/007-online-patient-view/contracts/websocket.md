# Contract: `WS /ws/session`

Handshake: refused (close before accept, HTTP 403) when the `Origin` is not allowed or the cookie
is not a valid sign-in. The patient is taken from the sign-in. Text frames only, 4 KB maximum.

## Client to service

| Message | Meaning |
|---------|---------|
| `{"type":"start","pose_model":"movenet-lightning-4"}` | Begin. The service picks the first program exercise not done today (all done: the first). |
| `{"type":"frame","k":[51 numbers],"w":1280,"h":720}` | 17 points as x, y, score in the video's pixel space, COCO order. Sent at a steady 15 per second. `k` may be null when nobody is seen. |
| `{"type":"next"}` | Move to the next exercise (ignored on the last one). |
| `{"type":"stop"}` | End as completed. |

## Service to client

| Message | When |
|---------|------|
| `{"type":"state","exercise":"Knee Extension","index":1,"total":2,"target_reps":10,"rep_count":3,"phase":"up","angle":171.2,"form_status":"good","form_messages":["..."],"feedback":"Rep 3 complete!","set_complete":false,"seen":true}` | After `start`, on any change, and at most five times a second otherwise |
| `{"type":"notice","code":"low_rate"|"no_person"|"setup_incomplete"}` | Conditions the page words for the patient |
| `{"type":"refused","reason":"second_device"|"no_program"|"busy"}` then close | `start` cannot be honoured |
| `{"type":"ended","status":"completed","summary":{"exercises":[{"name":"Knee Extension","reps":10}],"total_reps":19,"avg_form_score":87.5}}` then close | After `stop`, or the idle or length limit |

## Rules

- The service owns the frame counter and every stored time; client times are ignored.
- More than 20 frames in any second: the extra ones are dropped, not queued, and counted.
- Ten invalid messages: close with code 1008 and write `live_refused` with detail `bad_frames`.
- `set_complete` becomes true when the target is reached; the page then offers next or stop. The
  service does not switch on its own.
- Close without `stop`, or a revoked code (checked every five seconds): the session is interrupted
  with reason `portal_disconnected` or `access_revoked`; every recorded event is kept.
- Sixty seconds without a frame, or sixty minutes of session: ended as completed with an `ended`
  message when the socket is still open.
