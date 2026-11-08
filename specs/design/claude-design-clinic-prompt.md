# Prompt for Claude Design — Limber clinic app

Copy everything below the line into Claude Design. If you can, attach `design/limber-export/screens/limber.css` and
one or two patient screens, such as `Today.html`, so it can match them.

---

Design the therapist and admin side of **Limber**, a physical-therapy app that helps patients between clinic visits. The patient side already exists. This is a new, full redesign of the clinic side, built as plain HTML, CSS and a little JavaScript. **There are no framework limits. Do not design around Streamlit or any component library.**

## What is wrong today, and must not come back

The current clinic side is cluttered and feels like a generic data tool:

- a wide left sidebar with 13 links;
- pickers stacked above the content (choose a row, then a conversation, then a plan);
- tables used as menus;
- big rows of stat tiles, emoji in headings, full-width banners pushing the real work down the page.

Do not copy another physical-therapy product. Limber needs its own look.

## What it should feel like

Calm, quiet and quick, like a well-made email app. A therapist between patients should see what needs them within seconds. Use plenty of white space, few borders, one clear action per area. Secondary controls stay out of the way until needed. Plain words and short sentences throughout.

## Brand (keep it, so both sides feel like one product)

- Colours: teal `#0E6B64` (primary), teal-dark `#0A544E`, coral `#F2684A` (accent, alerts), ink `#16302C` (text), muted `#728280` (icons only), muted-text `#5E6E6C` (small text), background `#FAF8F4`, card `#FFFFFF`, line `#EDEAE2`, line-strong `#D6D1C5`, warning `#B4432B`, teal-tint `#E3EFED`, coral-tint `#FDEBE5`, warn-tint `#FBECE8`. Unread badges are ink on coral, never white on coral.
- Type: Sora (fallback Outfit, system sans). Headings 800 weight, tight letter-spacing (-0.02em). The scale may be tighter than the patient side because this is a work tool, but say what you changed.
- Shapes: flat, no drop shadows on content. Patient-side cards use a 22px radius and controls 14px. You may reduce these for density, but it must still look like Limber.

## Who uses it

Therapists and clinic admins on a laptop. Design at **1280px**, and show the Inbox and patient page at **1024px**. Patients are identified only by a code such as **P-021**, never a name, photo, email or birth date. Staff have display names.

## Layout (the owner chose this)

**A slim top bar, with a split view below it.**

```
Limber   Inbox 5  Patients  Schedule     [Find a patient]   Tools ▾   Me ▾
---------------------------------------------------------------------------
Needs you (5)      | P-021 · Right hip replacement
> P-021  1 new     | Started 3 weeks ago · Next visit Tue 4 Nov, 9:00
  P-023  ! urgent  |
  P-017  3 new     |   conversation or patient detail
  P-021  reschedule|
                   |   [Reply...]                     [Draft a reply]
```

- **Tools** menu: Dashboard, Live session, Video analysis, Sessions, Observation logs, Review, Tracker, How it works.
- **Me** menu: My settings, People (admins only), Sign out. Show the signed-in name.
- An admin-only account sees only People and My settings.

## Screens and states

**Daily work**

1. **Inbox.** One "Needs you" list that mixes unread messages (with the plan of care named), reschedule requests and red flags, most urgent first. Selecting an item opens it on the right. Show:
   - the thread with photo thumbnails, PDF chips and voice notes (player, plus an automatic transcript labelled as possibly containing mistakes);
   - the reply box with attachments (up to 4 photos or 1 PDF);
   - the warning when a reply looks like it holds a phone number or name, with **Send anyway**;
   - **Draft a reply**: idle, drafting (a few seconds), and draft in the box labelled "AI-drafted — check before sending". It is never sent automatically, and it can be edited or discarded;
   - the **withheld** state: "This message may need a direct response", quoting the patient's words, for example "had a fall", with **Mark as handled by phone**;
   - a reschedule request answered from here;
   - switching messaging on or off for a patient;
   - an archived plan, read-only;
   - empty state ("Nothing needs you right now"), loading, and error.
2. **Patients.** A patient list on the left (code, plan, one status line such as "Pain rising" or "Inactive 2 weeks"), with **Register a patient**, and the chosen patient on the right. Sections:
   - **Overview**: days done, pain with its change, next visit, and the **Weekly summary**: Summarise the last 7 days, loading, the result with 1–3 next steps linking to records, labelled "AI-drafted — check before acting", then Save as session note, Edit, Discard. Also "No records this week" and "The assistant isn't available right now";
   - **Exercises**: the assigned program, assigning or changing one;
   - **Messages**: the same conversation view as the Inbox;
   - **Session notes**;
   - **AI settings**: two switches, Weekly summaries and drafts, and Patient exercise coach, both off by default, each with the plain-words notice the patient is shown, plus a read-only log of past coach conversations (answered, sent to you, emergency card shown);
   - **Details**: plans of care (open, complete, archive; diagnosis, with a choice to show it to the patient), visits (add, change, cancel), questionnaires, what the patient can log, home access (issue or revoke an access code, shown once), caseload status (discharge, reactivate), label and notes, and delete with a strong confirmation.
   - Links to this patient's **Review** and **Sessions**.
3. **Schedule.** Reschedule requests first with the patient's note, then upcoming visits, then past ones. Cancelled visits struck through, and past ones marked "past". Consider a week view if it stays calm.

**Tools** (they get less attention day to day, but must be just as clean)

4. **Dashboard.** A short overview: observation sessions, total reps, average form score, average range of motion, and recent sessions from real records. Avoid the stat-tile row look.
5. **Live session.** Choose a patient and exercise, camera view with a body-point overlay, rep counter, range of motion, form feedback, Start/Next/Stop, then a finished summary. State plainly that video stays in the browser and only 17 body points are sent. Show camera-blocked and model-loading states.
6. **Video analysis.** Upload, exercise choice, options (annotated video, detailed report), a progress state for a job that takes minutes, then results with the original and annotated video, per-rep measures and downloads.
7. **Sessions.** A filterable list with export (formats shown as a simple choice).
8. **Review.** One patient over time: first → latest, measure charts (range of motion, form score), per-session summary, attention thresholds, goals, patient videos, reported exercise diary, medication taken, sleep, questionnaires, pain and symptom check-ins, and downloads. This is the densest page, so give it clear structure, perhaps a section list on the left. Show a section with no data.
9. **Tracker.** The caseload at a glance, with who needs attention and why, roster export, and installation thresholds.
10. **Observation logs.** A session list, then charts (form score per rep, range of motion per rep, rep duration, joint angle range), a rep-by-rep table, an event timeline, warnings and downloads.
11. **How it works.** A plain explanation of how reps, range of motion and form are measured, with a small form score calculator. No stock images.

**Admin**

12. **People.** Accounts with role and status, invite someone (therapist, admin, or patient assigned to a therapist) with a link to copy, revoke an unused invite, disable or re-enable, reassign patients.
13. **My settings.** Larger text, Higher contrast, Less motion. These follow you to every device.
14. **First-run setup message** when no staff password is set, and **signed-out** when the sign-in has ended, keeping any typed reply.

## Rules the design must respect

- **AI is always labelled** in the same consistent way. Nothing AI-written reaches a patient without the therapist pressing Send, except the coach, which the therapist turned on.
- **Numbers carry meaning**: every metric shows its unit and a plain definition (range of motion in degrees; form score 0–100). Show how the definition appears (for example, on hover and focus, and in text).
- **Every chart** has a table or text equivalent. Charts are simple lines and bars that can be drawn with plain SVG.
- **Accessibility**: WCAG 2.2 AA, targets at least 24px and 44px for main actions, full keyboard use with visible focus, and never colour alone for meaning, including urgent items and unread state. Show the Inbox and a patient page once in **Larger text + Higher contrast** (Higher contrast must reach AAA).
- **No outside resources**: no CDN, icon font or remote image. Inline SVG icons only.
- **Safety cues** are unmistakable but not alarming. Reserve warning colours for things that truly need attention.

## Sample data

- Therapist: "Therapist". Patients: P-021 (Right hip replacement, plus Left shoulder; pain rose from 3/10 to 6/10 this week; 4 of 7 days done), P-023 (Shoulder; message says "I had a fall and now my foot is numb"), P-017 (Post-op knee; steady; 5-week streak; one archived plan).
- Reschedule request from P-021 for Fri 6 Nov, 09:00: "Afternoons are better for me this week."
- Exercises: Heel slides 3×10, Quad sets 3×15 (5-second hold), Straight-leg raises 2×10, Hip abduction 10 reps.
- Next visit: Tuesday 4 November, 9:00, 45 minutes, "Re-check range of motion".

## What to give back

1. Every screen and state above, at the widths given.
2. Plain **HTML + CSS** export, with no Tailwind or JS framework, using CSS custom properties named to match the colours above. List any new tokens and why each is needed.
3. A short component list (top bar, menu, needs-you row, thread, reply box, AI label, withheld notice, patient list row, section nav, chart, data table, confirm dialog, and so on) with each one's states.
4. All on-screen copy as text, so it can be reviewed separately.
