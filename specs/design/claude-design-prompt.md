# Prompt for Claude Design — Limber messaging and AI chat

Copy everything below the line into Claude Design.

---

Design the messaging and AI-assistant screens for **Limber**, a physical-therapy app that helps patients between clinic visits. The sign-in, onboarding, Today, Progress and Settings pages already exist. Your screens must look like they belong with them.

## Brand (already in use — keep it)

- Colours: teal `#0E6B64` (primary), teal-dark `#0A544E`, coral `#F2684A` (accent, to-do, alerts), ink `#16302C` (text), muted `#728280`, background `#FAF8F4` (warm off-white), card `#FFFFFF`, line `#EDEAE2`, warning `#B4432B`.
- Type: Sora (fallback Outfit, system sans). Headings 800 weight, tight letter-spacing (-0.02em). Body 17px / 1.5.
- Shapes: cards with 22px radius and a 1px line border, inputs and buttons with 14px radius, pill chips and badges. Flat, no drop shadows, generous white space.
- Tone: calm, plain words, short sentences. Written for adults of any age, many of them older or recovering from surgery.

## Who uses it

- **Patients** on a phone (design at 390px wide first, then show 768px). They are identified by a code like **P-021**, never by name.
- **Therapists** on a laptop (design at 1280px). The therapist app is built in Streamlit, so keep those screens to what Streamlit can do: a sidebar, stacked sections, columns, tables, text areas, buttons, expanders, tabs, and chat bubbles (`st.chat_message`). No drag-and-drop, no floating panels, no custom overlays.

## Screens to design

**Patient side**

1. **Messages, grouped by plan of care.** A patient can have more than one plan (e.g. "Right knee, post-op" and "Left shoulder"). Show:
   - a plan switcher with an unread count on each plan;
   - the conversation thread with the therapist;
   - a compose box that can attach up to 4 photos or 1 PDF, with photo thumbnails, a take-a-photo option on phones, and a remove control on each attachment;
   - the existing "Not for emergencies" note;
   - a warning that appears when the patient types something that looks like a phone number or name, with **Send anyway**;
   - an **archived plan** state: read-only, with no compose box and a short explanation.
2. **Exercise coach chat ("Ask about your exercises").** This is an AI chat that answers only from the patient's own exercise program. Show:
   - an empty state with 3 suggested questions;
   - a normal answer that names the exercise and its prescribed dose (e.g. "Heel slides — 3 sets of 10, bend until you feel a gentle stretch");
   - a clear but quiet label that answers come from an AI assistant using the patient's program, and that their therapist can read the chat;
   - a **"That's one for your therapist"** referral card with a **Message your therapist** button, used when someone asks about worsening pain, new symptoms, medication or changing the program;
   - an **emergency card** for red flags such as "my calf is swollen and hot": call 911 or go to the nearest emergency room. This card is the only thing shown — no AI text — and it must be unmistakable without being alarming;
   - a thinking/loading state (answers take a few seconds);
   - "the coach is turned off" and "you've reached today's question limit" states, each pointing to Messages.
3. **Today (update).** Add the existing home's new pieces: one card per active plan, the next appointment, and an entry point to the coach.
4. **Appointments.** An upcoming list and a month view, with cancelled appointments struck through and past ones marked "past". Include an **Ask to reschedule** sheet with a note field, and a "request sent" state.

**Therapist side (Streamlit-friendly)**

5. **Inbox.** A list of patients with unread counts per plan, then a conversation view showing attachments (thumbnails, PDF chips). Include a **Draft a reply** button. The draft lands in the reply box, labelled "AI-drafted — check before sending", and is never sent automatically. Also show a **withheld** state: "This message may need a direct response" (when the patient mentioned chest pain, a fall, numbness, and similar).
6. **Weekly summary panel** on a patient's page. Show:
   - a **Summarise the last 7 days** button and its loading state;
   - the result: a short summary covering adherence, pain trend and questions asked, plus 1–3 suggested next steps, each with a link to the records it came from;
   - the label "AI-drafted — check before acting";
   - **Save as session note**, **Edit**, and **Discard** buttons;
   - "No records this week" and "The assistant isn't available right now" states.
7. **AI settings per patient.** Two switches, Weekly summaries and drafts, and Patient exercise coach, both off by default. Each has the plain-words notice the patient is shown. Also show a read-only list of past coach conversations.

## Rules the design must respect

- Anything written by AI is labelled as AI, every time, in the same consistent way. Nothing the AI writes reaches a patient without the therapist except the coach, which the therapist turned on.
- Accessibility: WCAG 2.2 AA; tap targets at least 44px; never colour alone for meaning. The app has three user settings — **Larger text**, **Higher contrast** (must reach AAA), and **Less motion**. Show each new screen once in Larger text + Higher contrast to prove it holds up.
- Patient screens show the code (P-021), never a name, avatar photo, or email.
- Do not redesign sign-in, onboarding or the navigation bar (Today · Progress · Messages · Settings). You may add one nav item for the coach or appointments if you think it earns its place. Say why.

## Sample data

- Patient P-021, plan "Right knee, post-op", started 3 weeks ago. Exercises: Heel slides 3×10, Quad sets 3×15 (5-second hold), Straight-leg raises 2×10. Pain rose from 3/10 to 6/10 this week, and 4 of 7 days were done.
- Therapist message: "How did the stairs feel this week?" Patient reply: "Harder on Thursday, knee felt tight. Photo of the swelling attached."
- Next appointment: Tuesday 4 November, 9:00, 45 minutes, "Re-check range of motion".

## What to give back

1. Each screen and state listed above, at the widths given.
2. Plain **HTML + CSS** export, without Tailwind or a JS framework, using CSS custom properties named to match the colours above (`--teal`, `--coral`, `--ink`, `--muted`, `--bg`, `--card`, `--line`, `--warn`). Add new tokens only if needed, and list them.
3. A short component list (message bubble, attachment tray, AI label, referral card, emergency card, plan switcher, appointment row, and so on) with each one's states.
4. All on-screen copy as text, so it can be reviewed separately.
