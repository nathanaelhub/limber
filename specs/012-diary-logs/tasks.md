# Tasks: Exercise Diary, Medication and Sleep Logs

- [x] T001 Branch; spec; plan; tasks
- [x] T002 [P] Failing tests/test_ptlog_store_v11.py: a realistic v10 record upgrades with every table's count intact, foreign keys on and `foreign_key_check` empty; the new source and reported columns exist; a diary session round-trips
- [x] T003 Implement the v11 rebuild and the store methods (reported reps/sets/effort, medication list, diary switch)
- [x] T004 [P] Failing tests: `capture_origin` returns self-reported; adherence, done-today, streak, practice gap, and summary count diary; trends, flags, goal progress, comparison skip it; with no diary everything equals feature 011
- [x] T005 Implement origin, adherence, review, store summary changes
- [x] T006 [P] Failing tests: `src/portal/diary.py` validation and session building; medication and sleep entry kinds; HTTP routes (own data, refused when off or discharged, seven-day window, privacy-checked note); today view carries the diary switch and log options
- [x] T007 Implement diary rules, entry kinds, routes, diary.html and log.html
- [x] T008 [P] Failing AppTest: Patients page medication list and diary switch; From the patient shows diary, medication, sleep
- [x] T009 Implement in interfaces/app.py; CLI if needed
- [ ] T010 Demo data; docs (Update 14); phone-emulation run; record results; commit and merge
