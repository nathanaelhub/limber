# Quickstart: Online Patient View

For demo and study use only. Not for real clinic patients until a compliance review approves it.

## 1. Tests (no network, camera, model, or browser)

```bash
.venv/bin/python -m pytest tests -q
```

## 2. One-time setup of the pose assets

```bash
.venv/bin/python scripts/fetch_portal_assets.py      # about 6 MB, checked against recorded SHA-256
```

## 3. On this machine

```bash
.venv/bin/python scripts/seed_demo.py
export PTASSIST_DB=data/demo.db
python interfaces/cli.py portal code create P-017
python interfaces/cli.py portal serve                 # http://127.0.0.1:8600
```

Open the address, read the notice, enter the code. Expected: today's program for P-017 with target
reps; "Start session" asks for the camera, shows the mirrored video with a skeleton, counts reps,
offers the next exercise when the target is reached, and "Stop" shows a summary. Then in the
therapist app (`streamlit run interfaces/app.py`): the session is listed for P-017 as recorded at
`home`; Review trends show home and clinic series separately.

## 4. Access control

- A wrong code is refused with the same message as an expired one; the sixth wrong attempt in
  fifteen minutes is refused with a wait time.
- `portal code revoke P-017` while a session runs: the page signs out and the session is
  interrupted with its reps kept.
- `portal audit --patient P-017` lists the events without any code or address.
- Open the link in a second browser during a session and start: refused as a second device.

## 5. Two people at once

Start a home session for P-017 and a therapist Live Session (or a second patient's home session).
Expected: both stay `running`; stopping one leaves the other untouched.

## 6. From a phone (secure connection required)

```bash
python interfaces/cli.py portal serve --public-origin https://<tunnel-host> --trust-proxy
```

Run a temporary HTTPS tunnel to port 8600 and open its address on the phone. The tunnel operator
can see the body-point numbers in transit; say so in the study's consent text. Camera video never
leaves the phone.

## 7. Browser pose model check (scripted, outside the repo)

Chrome with a fake camera fed from the sample squat clip: the whole path works and four reps are
recorded. The model comparison already measured is in research D2.

## Manual verification

- **FR-002**: `portal serve --host 0.0.0.0` without a certificate exits with an explanation.
- **FR-009**: the browser's network panel shows only JSON messages of numbers during a session; no
  image or video request leaves the device.
- **FR-017**: the sign-in page states what is sent, what is not, and that this is for demo and
  study use.
- **FR-018**: the network panel shows every script and model file loaded from the service itself.

## Done criteria

Steps 1 to 5 pass; step 7 passes; `docs/UPDATES.md` has an entry. Step 6 is recorded as run or not run.
