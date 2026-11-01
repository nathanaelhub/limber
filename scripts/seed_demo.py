"""Build a simulated caseload for demos and manual testing.

    .venv/bin/python scripts/seed_demo.py                 # writes data/demo.db (replaced if present)
    PTASSIST_DB=data/demo.db streamlit run interfaces/app.py

Everything is invented. Patients have pseudonymous IDs and clinical labels only, never names.
The real record (data/ptassist.db) is never touched: the script refuses to write to it.
"""

from __future__ import annotations

import argparse
import tempfile
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.ptlog.models import ExerciseSetInfo, FormEvent, PartialRepEvent, RepEvent  # noqa: E402
from src.ptlog.store import SessionStore  # noqa: E402

EXERCISES = {  # display name -> (key, up angle, down angle, side)
    "Knee Extension": ("knee_extension", 170.0, 90.0, "left"),
    "Squat": ("squat", 170.0, 90.0, "bilateral"),
    "Partial Squat": ("partial_squat", 170.0, 120.0, "bilateral"),
    "Shoulder Flexion": ("shoulder_flexion", 170.0, 20.0, "left"),
    "Hip Abduction": ("hip_abduction", 45.0, 10.0, "left"),
    "Push-Up": ("pushup", 170.0, 90.0, "left"),
    "Elbow Flexion": ("elbow_flexion", 40.0, 160.0, "left"),
}
WARNINGS = ["Keep knee aligned over toes", "Trunk leaning forward", "Shoulders uneven", "Slow the lowering phase"]


class Clock:
    def __init__(self):
        self.now = datetime.now()

    def __call__(self):
        return self.now


def record(store, clock, rng, pid, name, days_ago, form, rom, reps=10, target=10, partials=0,
           warnings=0, stop=False, hour=9, source="webcam", interrupted=False, home=False):
    start = (datetime.now() - timedelta(days=days_ago)).replace(hour=hour, minute=rng.choice((0, 15, 30, 45)),
                                                                 second=0, microsecond=0)
    if start > datetime.now():
        start = datetime.now() - timedelta(hours=2)
    clock.now = start
    key, up, down, side = EXERCISES[name]
    extras = {"camera_id": 0, "imgsz": 320, "frame_skip": 1} if source == "webcam" else None
    if home:          # recorded by the patient at home through the Limber patient view (browser pose model)
        source, extras = "webcam", {"origin": "portal", "pose_model": "movenet-lightning-4", "fps_nominal": 15}
    sid = store.start_session(pid, source, "home" if home else ("0" if source == "webcam" else "home_clip.mp4"), extras)
    set_id = store.open_set(sid, ExerciseSetInfo(key, name, side, target, up, down))
    t = start
    for n in range(1, reps + 1):
        t += timedelta(seconds=rng.uniform(3.5, 5.0))
        r = max(5.0, rom + rng.uniform(-1.2, 1.2))
        low = min(up, down)
        store.add_rep(set_id, RepEvent(n, round(low, 1), round(low + r, 1), round(r, 1), round(rng.uniform(2.1, 3.2), 2),
                                       round(min(100.0, max(0.0, form + rng.uniform(-2.5, 2.5))), 1), t.isoformat(), 60 * n))
    for _ in range(partials):
        t += timedelta(seconds=3)
        store.add_partial_rep(set_id, PartialRepEvent("reversed_early", 130.0, 165.0, 35.0, 1.4, t.isoformat(), 0))
    for i in range(warnings):
        store.add_form_event(set_id, FormEvent("warning", "warning", rng.choice(WARNINGS),
                                               (start + timedelta(seconds=15 + 20 * i)).isoformat(), 300 + 600 * i, "trunk"))
    if stop:
        store.add_form_event(set_id, FormEvent("stop", "stop", "Knee collapsing inward: stop and reset",
                                               (start + timedelta(seconds=30)).isoformat(), 900, "knee"))
    clock.now = t + timedelta(seconds=6)
    if not interrupted:
        store.end_session(sid)
    return sid


def ramp(a, b, n):
    return [a + (b - a) * i / max(1, n - 1) for i in range(n)]


def build(db_path: Path, seed: int = 7) -> None:
    rng = random.Random(seed)
    clock = Clock()
    today = date.today()
    with SessionStore(db_path, clock=clock).open() as s:

        def review_all(pid, step="continue", leave=0):
            rows = s.list_sessions(pid)                       # newest first
            for row in rows[leave:]:
                s.set_review(row.id, step if row.id % 4 else "progress")

        # P-017: post-op knee. Good early progress, knee ROM slipped this week; squat stuck under target.
        s.add_patient("P-017", label="Post-op knee, week 6")
        days = [40, 37, 34, 30, 27, 23, 20, 16, 12, 9, 6, 2]
        knee_rom = ramp(62, 86, 9) + [85, 87, 80]
        for d, rom, form in zip(days, knee_rom, ramp(78, 89, 11) + [85]):
            record(s, clock, rng, "P-017", "Knee Extension", d, form, rom, warnings=1 if d == 2 else 0)
            record(s, clock, rng, "P-017", "Squat", d, 82, 92 + (40 - d) * 0.15, reps=9, hour=10, partials=1 if d < 8 else 0)
        # ...and practises at home between visits; home numbers sit on their own scale (different pose model)
        for d, rom in zip([10, 7, 4, 1], [79, 80, 82, 83]):
            record(s, clock, rng, "P-017", "Knee Extension", d, 86, rom, hour=18, home=True)
            record(s, clock, rng, "P-017", "Squat", d, 80, 104, reps=10, hour=18, home=True)
        review_all("P-017", leave=2)
        s.assign_program("P-017", "knee_rehab", "Knee Rehabilitation", ["knee_extension", "squat"], 3, today - timedelta(days=35))
        s.set_goal("P-017", "Knee Extension", target_rom=95.0, target_reps=10)

        # P-018: shoulder. Progressed well, then nothing for 12 days.
        s.add_patient("P-018", label="Shoulder impingement")
        for d, rom in zip([38, 35, 31, 28, 24, 21, 17, 12], ramp(108, 140, 8)):
            record(s, clock, rng, "P-018", "Shoulder Flexion", d, 90, rom)
        review_all("P-018", step="progress")
        s.assign_program("P-018", "shoulder_mobility", "Shoulder Mobility", ["shoulder_flexion"], 2, today - timedelta(days=35))
        s.set_goal("P-018", "Shoulder Flexion", target_rom=150.0)

        # P-019: conditioning. Steady and adherent; a quiet row on the roster.
        s.add_patient("P-019", label="General conditioning")
        for d in [33, 31, 29, 26, 24, 22, 19, 17, 15, 12, 10, 8, 5, 3, 1]:
            record(s, clock, rng, "P-019", "Squat", d, 91, 98, reps=12, target=12)
            if d % 2:
                record(s, clock, rng, "P-019", "Push-Up", d, 88, 82, reps=10, hour=11)
        review_all("P-019")
        s.assign_program("P-019", "general_conditioning", "General Conditioning", ["squat", "pushup"], 3, today - timedelta(days=35))

        # P-021: hip. Form score falling session after session, partial reps rising.
        s.add_patient("P-021", label="Hip replacement, week 10")
        for d, form, partials in zip([22, 18, 15, 11, 8, 4, 1], [92, 91, 90, 86, 82, 77, 71], [0, 0, 0, 1, 1, 3, 5]):
            record(s, clock, rng, "P-021", "Hip Abduction", d, form, 32, partials=partials, warnings=2 if d < 9 else 0)
        review_all("P-021", leave=3)
        s.assign_program("P-021", "hip_strengthening", "Hip Strengthening", ["hip_abduction"], 3, today - timedelta(days=21))

        # P-022: knee OA. ROM flat for weeks while below the goal (plateau).
        s.add_patient("P-022", label="Knee osteoarthritis")
        for d, rom in zip([26, 22, 19, 15, 12, 8, 5, 2], [70, 72, 73, 74, 74.5, 74, 75, 74.5]):
            record(s, clock, rng, "P-022", "Partial Squat", d, 87, rom, source="video" if d % 3 == 0 else "webcam")
        review_all("P-022", step="hold", leave=1)
        s.set_goal("P-022", "Partial Squat", target_rom=90.0)
        s.assign_program("P-022", "custom", "Knee OA home program", ["partial_squat"], 3, today - timedelta(days=28))

        # P-023: ACL return to sport. A safety stop last session, and low adherence.
        s.add_patient("P-023", label="ACL reconstruction, month 5")
        for d in [27, 20, 13, 3]:
            record(s, clock, rng, "P-023", "Squat", d, 84, 101, stop=(d == 3))
        review_all("P-023", leave=1)
        s.assign_program("P-023", "knee_rehab", "Knee Rehabilitation", ["squat", "knee_extension"], 3, today - timedelta(days=28))

        # P-024: elbow. A session interrupted by a closed tab, otherwise fine.
        s.add_patient("P-024", label="Elbow fracture, post-cast")
        for d, rom in zip([14, 11, 7, 4], ramp(85, 104, 4)):
            record(s, clock, rng, "P-024", "Elbow Flexion", d, 89, rom)
        lost = record(s, clock, rng, "P-024", "Elbow Flexion", 1, 88, 105, reps=4, interrupted=True)
        s.interrupt_session(lost, "stream_lost")
        review_all("P-024", leave=1)

        # P-020: new referral, nothing recorded yet.  P-016: discharged after meeting goals.
        s.add_patient("P-020", label="New referral")
        s.add_patient("P-016", label="Ankle sprain")
        for d in [60, 56, 52, 48]:
            record(s, clock, rng, "P-016", "Partial Squat", d, 93, 88)
        review_all("P-016", step="progress")
        s.discharge("P-016", on=today - timedelta(days=45), reason="Goals met, independent with home program")

        # Conversations (feature 008): some answered, some waiting for a reply.
        from src.portal import messages
        talk = [
            ("P-017", 3, "patient", "My knee felt stiff this morning. Is that normal after the stairs exercise?"),
            ("P-017", 3, "therapist", "Some stiffness is expected. Keep the reps slow, and ice for ten minutes afterwards."),
            ("P-017", 0.2, "patient", "Thanks. Today the last three reps were hard. Should I stop at seven?"),
            ("P-021", 1, "patient", "I could not finish the hip set today, it pinched on the outside."),
            ("P-021", 0.5, "patient", "It is fine when I rest."),
            ("P-023", 5, "therapist", "Please keep squats shallow until I see you on Thursday."),
        ]
        for pid in ("P-017", "P-021", "P-023"):
            clock.now = datetime.now() - timedelta(days=6)
            messages.set_enabled(s, pid, True)
        for pid, days_ago, sender, text in talk:
            clock.now = datetime.now() - timedelta(days=days_ago)
            messages.send(s, pid, sender, text)
        clock.now = datetime.now() - timedelta(days=2)
        messages.thread(s, "P-017", viewer="patient")            # the patient has read the first reply

        # Pain check-ins (feature 010): P-017 steady then a jump; P-021 climbing.
        for pid, series in (("P-017", [(9, 3), (7, 2), (5, 3), (3, 2), (1, 6)]), ("P-021", [(8, 4), (6, 5), (4, 6), (2, 7), (1, 8)])):
            for i, (days_ago, pain) in enumerate(series):
                when = datetime.now() - timedelta(days=days_ago, hours=1)
                s.entry_add(pid, "checkin", {"pain": pain, "area": "knee" if pid == "P-017" else "hip",
                                             "stiffness": "mild" if pain < 5 else "moderate", "swelling": "none",
                                             "note": "Pinching on the outside of the hip." if pid == "P-021" and i == 4 else ""},
                            float(pain), when.isoformat(), f"demo-{pid}-{i}", "standalone", None, False, False)

        # Exercise logged without the camera, medication, and sleep (feature 012).
        from src.portal import diary
        s.set_medication_list("P-017", ["ibuprofen 400 mg", "paracetamol 1 g"])
        s.set_medication_list("P-021", ["naproxen 250 mg"])
        s.set_diary_enabled("P-023", False)                      # one patient the therapist turned it off for
        logged = [("P-017", "knee_extension", 4, 12, 2, 3, ""),
                  ("P-017", "squat", 2, 10, 2, 4, "Did these in the park."),
                  ("P-019", "knee_extension", 3, 10, 3, 2, ""),
                  ("P-019", "knee_extension", 1, 10, 3, 3, "No room to set the phone up."),
                  ("P-021", "hip_abduction", 2, 8, 2, 5, "Felt it pinch again.")]
        for pid, key, days_ago, reps, sets, effort, note in logged:
            when = datetime.now() - timedelta(days=days_ago, hours=3)
            clock.now = when
            diary.log(s, pid, {"exercise": key, "reps": reps, "sets": sets, "effort": effort,
                               "note": note, "done_at": when.isoformat()}, now=when)
        for pid, item, days_ago in (("P-017", "ibuprofen 400 mg", 2), ("P-017", "paracetamol 1 g", 1),
                                    ("P-021", "naproxen 250 mg", 1)):
            when = datetime.now() - timedelta(days=days_ago, hours=2)
            s.entry_add(pid, "medication", {"item": item, "note": ""}, None, when.isoformat(),
                        f"demo-med-{pid}-{days_ago}", "standalone", None, False, False)
        for pid, nights in (("P-017", [(5, 7.5, 4), (4, 7.0, 4), (3, 6.5, 3), (2, 8.0, 5), (1, 7.5, 4)]),
                            ("P-021", [(4, 5.5, 2), (3, 5.0, 2), (2, 4.5, 1), (1, 6.0, 2)])):
            for days_ago, hours, quality in nights:
                when = datetime.now() - timedelta(days=days_ago, hours=14)
                s.entry_add(pid, "sleep", {"hours": hours, "quality": quality,
                                           "note": "Woke with the hip." if pid == "P-021" and quality == 1 else ""},
                            float(quality), when.isoformat(), f"demo-sleep-{pid}-{days_ago}", "standalone",
                            None, False, False)
        clock.now = datetime.now()

        # Questionnaires (feature 013): one patient answering twice, one overdue, one just assigned.
        from src.portal import questionnaires as portal_q
        from src.ptlog import instruments as instrument_files
        instrument_files.forget()
        demo_instrument = "demo_knee_function"
        if demo_instrument in instrument_files.load().by_key:
            s.assign_instrument("P-017", demo_instrument, "fortnightly", (datetime.now() - timedelta(days=30)).date())
            s.assign_instrument("P-019", demo_instrument, "monthly", (datetime.now() - timedelta(days=45)).date())
            s.assign_instrument("P-021", demo_instrument, "weekly", (datetime.now() - timedelta(days=20)).date())
            s.assign_instrument("P-023", demo_instrument, "weekly", datetime.now().date())   # due today
            better = {"stairs_up": 4, "stairs_down": 3, "rising": 3, "standing": 3, "walking": 4,
                      "kneeling": 2, "squatting": 2, "twisting": 3, "pain_moving": 1, "pain_night": 1}
            worse = {**better, "stairs_up": 2, "stairs_down": 1, "rising": 1, "walking": 2,
                     "pain_moving": 3, "pain_night": 2}
            for days_ago, answers in ((26, worse), (5, better)):
                when = datetime.now() - timedelta(days=days_ago, hours=5)
                payload, total = portal_q.accept(s, "P-017", {"instrument": demo_instrument, "answers": answers})
                s.entry_add("P-017", "questionnaire", payload, total, when.isoformat(),
                            f"demo-q-P-017-{days_ago}", "standalone", None, False, False)
            partial = {k: v for k, v in list(better.items())[:8]}          # eight of ten: within the rule
            when = datetime.now() - timedelta(days=12, hours=4)
            payload, total = portal_q.accept(s, "P-019", {"instrument": demo_instrument, "answers": partial})
            s.entry_add("P-019", "questionnaire", payload, total, when.isoformat(),
                        "demo-q-P-019", "standalone", None, False, False)   # P-019 is now overdue for the next one

        # A voice note in the inbox (feature 014), with nothing written out: the demo record must show
        # what the therapist sees on an installation without a speech model.
        import hashlib as _hashlib
        from src.portal import uploads as _uploads, voice as _voice
        from tests.fixtures import media as _media_fx
        try:
            note_path = Path(tempfile.mkdtemp()) / "note.m4a"
            _media_fx.make_audio(note_path, seconds=18.0, rate=16000, chunk=16000)
            audio = note_path.read_bytes()
            clock.now = datetime.now() - timedelta(hours=10)    # after P-021's last written message, so the thread reads in order
            up = _uploads.begin(s, s.media_dir, "P-021", "voice", len(audio),
                                _hashlib.sha256(audio).hexdigest(), chunk_bytes=len(audio))
            _uploads.put_part(s, s.media_dir, "P-021", up.id, 0, audio)
            _voice.finish(s, s.media_dir, "P-021", up.id)
        except Exception as exc:                          # a demo record is not worth failing the seed over
            print(f"  (no demo voice note: {exc})")
        clock.now = datetime.now()

        # Plans of care, a photo, and visits (feature 017).
        import io as _io
        from PIL import Image as _Image, ImageDraw as _Draw
        from src.portal import plans as _plans
        hip = s.plans("P-021")[0]
        _plans.edit_plan(s, s.plans("P-017")[0].id, title="Post-op knee", start_date=(today - timedelta(days=42)).isoformat())
        _plans.edit_plan(s, s.plans("P-023")[0].id, title="ACL reconstruction",
                         start_date=(today - timedelta(days=150)).isoformat())
        _plans.edit_plan(s, hip.id, title="Right hip replacement", diagnosis="Total hip arthroplasty, week 10",
                         start_date=(today - timedelta(days=70)).isoformat())
        clock.now = datetime.now() - timedelta(days=4)
        shoulder = _plans.open_plan(s, "P-021", "Left shoulder", diagnosis="Rotator cuff tendinopathy",
                                    diagnosis_visible=True)
        clock.now = datetime.now() - timedelta(days=3, hours=5)
        messages.send(s, "P-021", "therapist", "I've opened a separate plan for your shoulder so the two don't get "
                      "mixed up. Exercises for it come at your next visit.", plan_id=shoulder.id)
        photo = _Image.new("RGB", (640, 480), (232, 214, 200))
        pen = _Draw.Draw(photo)
        pen.ellipse((210, 140, 430, 340), fill=(214, 168, 150))
        pen.rectangle((0, 400, 640, 480), fill=(120, 140, 150))
        jpg = _io.BytesIO()
        photo.save(jpg, "JPEG", quality=85)
        clock.now = datetime.now() - timedelta(hours=9)
        messages.send(s, "P-021", "patient", "Photo of the outside of the hip, where it pinches.", plan_id=hip.id,
                      files=[("image/jpeg", jpg.getvalue())], media_dir=s.media_dir)
        # an earlier episode for P-017, finished and archived: read-only on both sides
        clock.now = datetime.now() - timedelta(days=130)
        ankle = _plans.open_plan(s, "P-017", "Left ankle sprain", start=(datetime.now() - timedelta(days=130)).date())
        clock.now = datetime.now() - timedelta(days=96)
        messages.send(s, "P-017", "therapist", "You have finished every exercise in this plan. Well done.", plan_id=ankle.id)
        clock.now = datetime.now() - timedelta(days=95)
        messages.send(s, "P-017", "patient", "Thank you for all the help.", plan_id=ankle.id)
        clock.now = datetime.now() - timedelta(days=94)
        _plans.complete(s, ankle.id)
        _plans.archive(s, ankle.id)
        clock.now = datetime.now()
        at = lambda days, hhmm: f"{(today + timedelta(days=days)).isoformat()}T{hhmm}"   # noqa: E731
        _plans.schedule(s, "P-017", at(-10, "10:30"), 45, "Range of motion check")
        _plans.schedule(s, "P-017", at(3, "10:30"), 45, "Progress squats if the knee is calm")
        nxt = _plans.schedule(s, "P-021", at(5, "09:00"), 45, "Re-check hip strength", plan_id=hip.id)
        _plans.request_reschedule(s, "P-021", nxt.id, "Afternoons are better for me this week.")
        _plans.cancel(s, _plans.schedule(s, "P-021", at(12, "14:00"), 30, "Shoulder assessment", plan_id=shoulder.id).id)
        _plans.schedule(s, "P-021", at(19, "14:00"), 30, "Shoulder assessment", plan_id=shoulder.id)
        _plans.schedule(s, "P-023", at(2, "16:00"), 60, "Return-to-sport testing")

        # Threshold settings with a history to look at.
        clock.now = datetime.now() - timedelta(days=9)
        s.set_installation_threshold("adherence", 65)
        clock.now = datetime.now() - timedelta(days=6)
        s.set_patient_threshold("P-019", "adherence", 50)
        s.set_patient_threshold("P-018", "practice_gap", 10)
        clock.now = datetime.now() - timedelta(days=1)
        s.set_exercise_threshold("P-017", "Knee Extension", "rom_regression", 5)
        clock.now = datetime.now()
        patients = len(s.list_patients())
        sessions = s.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    print(f"Wrote {db_path}: {patients} patients, {sessions} sessions (all simulated).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", default=str(REPO / "data" / "demo.db"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    db = Path(args.db).resolve()
    if db.name == "ptassist.db":
        print("Refusing to write simulated data into the real record (ptassist.db). Choose another --db.")
        return 1
    db.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    build(db, args.seed)
    write_demo_logins(db)
    return 0


DEMO_PASSWORD = "limber-demo-2026"
DEMO_PATIENTS = (("P-017", "knee, steady progress"), ("P-021", "hip, pain rising"), ("P-023", "shoulder, diary off"))


DEMO_SECOND_CASELOAD = ("P-018", "P-022", "P-024")   # rivera's patients; everyone else is the lead therapist's


def write_demo_logins(db_path: Path) -> None:
    """Test sign-ins for the demo record, printed and saved to data/demo-logins.txt (gitignored with the rest of
    data/): the installation therapist (also an admin), a second therapist with their own caseload, an admin who
    is not a therapist, a patient with a username, and a fresh access code per demo patient (feature 016).
    Demo record only: codes are issued against the demo database's own server key."""
    from src.portal import access, accounts, admin
    with SessionStore(db_path).open() as s:
        lead = admin.set_password(s, DEMO_PASSWORD)
        if s.account_by_username("rivera") is None:
            rivera = accounts.create_account(s, username="rivera", display_name="Dr. Rivera (demo)",
                                             password=DEMO_PASSWORD, role="therapist")
            accounts.create_account(s, username="admin", display_name="Clinic admin (demo)", password=DEMO_PASSWORD,
                                    role="admin")
            for pid in [p.id for p in s.list_patients() if not p.is_builtin]:
                accounts.assign(s, pid, rivera.id if pid in DEMO_SECOND_CASELOAD else lead.id)
            accounts.create_account(s, username="patient017", display_name="Demo patient", password=DEMO_PASSWORD,
                                    role="patient", patient_id="P-017")
        key = access.load_key(access.default_key_path(db_path))
        codes = [(pid, about, access.issue_code(s, key, pid, days=30)[0]) for pid, about in DEMO_PATIENTS]
    lines = [
        "Limber demo sign-ins (simulated data only; reissued every time the demo is rebuilt)",
        "",
        "Start it:  PTASSIST_DB=data/demo.db .venv/bin/python interfaces/cli.py portal serve",
        "           PTASSIST_DB=data/demo.db .venv/bin/streamlit run interfaces/app.py --server.port 8501",
        "Open:      http://127.0.0.1:8600",
        "",
        f"Every password below is  {DEMO_PASSWORD}",
        "Therapist door:",
        "  therapist   admin + therapist: every demo patient except the three below, and the People page",
        f"  rivera      therapist: only {', '.join(DEMO_SECOND_CASELOAD)}",
        "  admin       admin only: People and My settings, no clinical pages",
        "Patient door, 'I have a username and password':",
        "  patient017  P-017",
        "Patient door, access codes:",
    ] + [f"  {code}  {pid} ({about})" for pid, about, code in codes]
    out = db_path.parent / "demo-logins.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n(saved to {out})")


if __name__ == "__main__":
    raise SystemExit(main())
