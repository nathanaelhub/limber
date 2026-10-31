# Limber: on-screen copy

Extracted from the screens, in order. Frame captions are headings. Text in [brackets] is for screen readers or placeholders.


## Limber system

LIMBER · MESSAGING AND AI ASSISTANT
One calm system for talking to your therapist
Patient screens at 390 and 768. Therapist screens at 1280, built only from Streamlit parts. Same tokens as sign in, onboarding, Today, Progress and Settings.
Colour tokens
--teal
#0E6B64 · 6.4:1 on white
--teal-dark
#0A544E · 8.8:1 AAA
--coral
#F2684A · fills only, ink text on it
--ink
#16302C · 13.3:1
--muted
#728280 · 3.8:1, icons only
--warn
#B4432B · 5.6:1
--bg
#FAF8F4
--card
#FFFFFF
--line
#EDEAE2
New tokens
--muted-text
#5E6E6C · 5.1:1 small text
--line-strong
#D6D1C5 · input edges
--teal-tint
#E3EFED · selected, AI
--coral-tint
#FDEBE5 · to do
--warn-tint
#FBECE8 · warning
--scrim
ink at 48%
The AI label, every time
One mark, a boxed “AI”, plus words. Never colour alone, never an icon alone. The same mark appears on patient and therapist screens.
ON EACH COACH ANSWER
AI
AI assistant
TOP OF THE COACH CHAT
AI
Answers come from an AI assistant using your exercise program. Your therapist can read this chat.
THERAPIST REPLY BOX
AI
AI-drafted — check before sending
THERAPIST SUMMARY
AI
AI-drafted — check before acting
SET SAFETY MESSAGES (NOT AI)
Referral and emergency cards are fixed text written by the clinic. They carry no AI mark and say “This is a set message from your clinic.”
Navigation: one new item, Visits
[aria-label: Main]
Today
Progress
Messages
Visits
Settings
Visits sits before Settings. Every patient has visits, so the tab never disappears. Changing a visit is a task people come back to.
The coach does not get a tab. It is off by default, so a tab would vanish for many patients. It lives on Today and at the top of Messages instead.
Type
Heading 28 / 800
Card title 19 / 800
Body 17 / 1.5. Short sentences, plain words.
Small 15 / 600 for chips and buttons
Caption 13 in --muted-text, never --muted
Sora, then Outfit, then system sans.
The three user settings
Larger text.
Body 21, small 18, captions 16. Bubbles and cards grow taller, never truncate. Chips wrap to two rows.
Higher contrast (AAA).
Muted text becomes ink, teal becomes teal-dark (8.8:1), borders become 2px ink, tints become white, badges become ink with white text.
Less motion.
Thinking dots stop and the words “Checking your program” carry the meaning. Sheets appear without sliding.
Rules held on every screen
Patients are shown as a code such as P-021. No names, photos or emails.
Tap targets 44px or larger. Most are 48.
Status is always words plus shape: “2 new”, “Cancelled”, “Past”, “Done for today”.
Nothing written by AI reaches a patient without the therapist, except the coach, which the therapist turns on.
Components and their states
Plan switcher.
Active plan, other plan with “N new”, no unread, past plan (archive icon). Wraps in Larger text.
Message bubble.
Therapist, you, with photos, with PDF, sending, sent with time, failed with Try again.
Attachment tray.
Empty, 1 to 4 photos, 4 of 4 (add disabled, says why), 1 PDF (photos disabled), uploading, remove on each.
Add menu.
Take a photo (phones only), Choose photos, Choose a PDF.
Compose box.
Empty (send disabled), typing, privacy warning, sending. Hidden for past plans.
Privacy warning.
Phone number found, name found. Actions: Edit message, Send anyway.
AI label.
Answer label, chat banner, AI-drafted reply, AI-drafted summary.
Coach answer.
Thinking, answer with source link, referral card, emergency card.
Referral card.
Default, after tap (“Your question is in a new message”).
Emergency card.
One state. Replaces any AI text. Call 911 and Find an emergency room.
Coach unavailable.
Turned off, daily limit reached, cannot connect. Each links to Messages.
Plan card.
To do, in progress, done for today, coach entry.
Appointment row.
Upcoming, next, reschedule requested, cancelled (struck through), past.
Month view day.
Plain, today (ring), visit (filled), cancelled (dashed and struck), past.
Reschedule sheet.
Open, sending, request sent.
Therapist parts (Streamlit).
Inbox row, chat_message, draft box, withheld notice, summary panel, toggle with notice, coach log expander.

## Messages, phone


### 1a · Thread
plan switcher with unread, coach entry
Messages
P-021
[aria-label: Plans of care]
Right knee, post-op
Left shoulder
1 new
Past plans
AI
Quick question about an exercise?
Ask the coach
Wednesday 29 October
Your therapist
How did the stairs feel this week?
10:14
Thursday 30 October
You
Harder on Thursday, knee felt tight. Photo of the swelling attached.
[aria-label: Open photo: swelling, 30 October]
Photo
18:12 · Seen
Not for emergencies. If you need help now, call 911.
[aria-label: Add photo or PDF]
Message to your therapist
[placeholder: Write a message]
[aria-label: Send]
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

### 1b · Compose with photos
3 of 4, remove on each
Messages
P-021
[aria-label: Plans of care]
Right knee, post-op
Left shoulder
1 new
Past plans
Thursday 30 October
You
Harder on Thursday, knee felt tight. Photo of the swelling attached.
18:12 · Seen
Today
Your therapist
Thanks. Could you send one from the side too, and one of the other knee?
08:40
3 of 4 photos
You can add 1 more
[aria-label: Attached photos]
Photo 1
[aria-label: Remove photo 1]
Photo 2
[aria-label: Remove photo 2]
Photo 3
[aria-label: Remove photo 3]
[aria-label: Add photo or PDF]
Message to your therapist
Here they are. Side view, front, and my other knee.
[aria-label: Send]
Not for emergencies. If you need help now, call 911.
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

### 1c · Add menu
take a photo on phones
Messages
P-021
Right knee, post-op
Left shoulder
1 new
Your therapist
Thanks. Could you send one from the side too, and one of the other knee?
Add to your message
Up to 4 photos, or 1 PDF.
Take a photo
Choose photos
Choose a PDF
Cancel

### 1d · Compose with a PDF
photos off while a PDF is attached
Messages
P-021
Right knee, post-op
Left shoulder
1 new
Past plans
Your therapist
If you have the letter from your surgeon, could you send it here?
Yesterday, 16:02
PDF
Surgeon letter.pdf
PDF · 240 KB
[aria-label: Remove Surgeon letter.pdf]
One PDF per message. To add photos instead, remove the PDF.
[aria-label: Add photo or PDF. Unavailable while a PDF is attached]
Message to your therapist
Here is the letter.
[aria-label: Send]
Not for emergencies. If you need help now, call 911.
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

### 1e · Privacy check
phone number or name found
Messages
P-021
Right knee, post-op
Left shoulder
1 new
Your therapist
How did the stairs feel this week?
Wednesday, 10:14
This looks like a phone number or a name
Messages are safer without personal details. Your clinic already has your contact details.
Edit message
Send anyway
[aria-label: Add photo or PDF]
Message to your therapist
Easier to talk. Call me on 615 555 0142, ask for Margaret.
[aria-label: Send]
Not for emergencies. If you need help now, call 911.
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

### 1f · Past plan
read only, no compose box
Messages
P-021
Right knee, post-op
Left ankle · ended
Monday 11 August
Your therapist
You have finished every exercise in this plan. Well done.
You
Thank you for all the help.
Tuesday 12 August
Your therapist
I have closed this plan. Your exercise history is still in Progress.
This plan ended on 12 August
You can read these messages, but you can't reply here. To ask something new, use an active plan.
Go to Right knee, post-op
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

## Messages, tablet


### 1g · Messages at 768
plans become a list beside the thread
Messages
P-021
[aria-label: Plans of care]
ACTIVE PLANS
Right knee, post-op
Week 3 · All read
Left shoulder
Week 1
1 new
PAST PLANS
Left ankle
Ended 12 August
AI
Exercise coach
Quick question about an exercise?
Ask the coach.
Right knee, post-op
With your therapist · Started 3 weeks ago
Wednesday 29 October
Your therapist
How did the stairs feel this week?
10:14
Thursday 30 October
You
Harder on Thursday, knee felt tight. Photo of the swelling attached.
[aria-label: Open photo: swelling, 30 October]
Photo
18:12 · Seen
[aria-label: Attached photos]
Photo 1
[aria-label: Remove photo 1]
Photo 2
[aria-label: Remove photo 2]
2 of 4 photos
Add
Message to your therapist
[placeholder: Write a message]
Send
Not for emergencies. If you need help now, call 911.
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

## Exercise coach, phone


### 2a · Empty
3 suggested questions
Today
P-021
Ask about your exercises
Right knee, post-op
AI
Answers come from an AI assistant using your exercise program. Your therapist can read this chat.
What would you like to know?
I can only answer from your program. For anything else, message your therapist.
[aria-label: Suggested questions]
How far should I bend in heel slides?
How long do I hold each quad set?
Which exercises are left for today?
Your question
[placeholder: Ask about an exercise]
[aria-label: Ask]
Not for emergencies. If you need help now, call 911.
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

### 2b · Thinking
a few seconds; dots stop with Less motion
Today
P-021
Ask about your exercises
Right knee, post-op
AI
Answers come from an AI assistant using your exercise program. Your therapist can read this chat.
You
How far should I bend in heel slides?
AI
AI assistant
Checking your program
This can take a few seconds.
Your question
[placeholder: Ask about an exercise]
[aria-label: Ask. Wait for the answer first]
Not for emergencies. If you need help now, call 911.
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

### 2c · Answer
names the exercise and its dose
Today
P-021
Ask about your exercises
Right knee, post-op
AI
Answers come from an AI assistant using your exercise program. Your therapist can read this chat.
You
How far should I bend in heel slides?
AI
AI assistant
Heel slides: 3 sets of 10.
Bend until you feel a gentle stretch, then slide your heel back out.
A gentle stretch is fine. If you feel sharp pain, stop and tell your therapist.
From your program: Heel slides
09:02
Your question
[placeholder: Ask about an exercise]
[aria-label: Ask]
Not for emergencies. If you need help now, call 911.
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

### 2d · Referral
worse pain, new symptoms, medicine, program changes
Today
P-021
Ask about your exercises
Right knee, post-op
AI
Answers come from an AI assistant using your exercise program. Your therapist can read this chat.
You
My knee pain is worse this week. Should I stop the leg raises?
That's one for your therapist
Questions about pain getting worse, new symptoms, medicine or changing your program need your therapist. The coach can't answer them.
Message your therapist
Your question is copied into a new message. You can change it before you send.
This is a set message from your clinic.
Your question
[placeholder: Ask about an exercise]
[aria-label: Ask]
Not for emergencies. If you need help now, call 911.
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

## Coach safety and limits


### 2e · Emergency
card only, no AI text
Today
P-021
Ask about your exercises
Right knee, post-op
You
My calf is swollen and hot.
Please get help now
What you described can be serious. It needs a doctor today, not at your next visit.
Call 911 or go to the nearest emergency room.
Call 911
Find the nearest emergency room
This is a set safety message from your clinic, not an AI answer.
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

### 2f · Coach turned off
points to Messages
Today
P-021
Ask about your exercises
Right knee, post-op
The coach is turned off
Your therapist hasn't turned on the exercise coach for this plan. You can still ask them anything in Messages.
Go to Messages
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

### 2g · Daily limit reached
points to Messages
Today
P-021
Ask about your exercises
Right knee, post-op
AI
Answers come from an AI assistant using your exercise program. Your therapist can read this chat.
You
How long do I hold each quad set?
AI
AI assistant
Quad sets: 3 sets of 15, holding each for 5 seconds.
Tighten the muscle on top of your thigh and press the back of your knee down.
From your program: Quad sets
You've reached today's question limit
You can ask the coach again tomorrow. For anything sooner, message your therapist.
Go to Messages
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

## Exercise coach, tablet


### 2h · Coach at 768
the program it answers from sits beside the chat
Today
P-021
Ask about your exercises
Right knee, post-op
AI
Answers come from an AI assistant using your exercise program. Your therapist can read this chat.
Your program
The coach answers only from this list.
Heel slides
3 sets of 10
Quad sets
3 sets of 15, hold 5 seconds
Straight leg raises
2 sets of 10
You
How far should I bend in heel slides?
AI
AI assistant
Heel slides: 3 sets of 10.
Bend until you feel a gentle stretch, then slide your heel back out.
A gentle stretch is fine. If you feel sharp pain, stop and tell your therapist.
From your program: Heel slides
You
Can I take an extra painkiller before I do them?
That's one for your therapist
Questions about pain getting worse, new symptoms, medicine or changing your program need your therapist. The coach can't answer them.
Message your therapist
Your question is copied into a new message. You can change it before you send.
This is a set message from your clinic.
Your question
[placeholder: Ask about an exercise]
Ask
Not for emergencies. If you need help now, call 911.
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

## Today, updated


### 3a · Today at 390
plan cards, next visit, coach entry
Monday 3 November
P-021
Good morning
NOV
4
NEXT VISIT · TOMORROW
Tuesday, 9:00 · 45 min
Re-check range of motion
Right knee, post-op
Week 3 · 3 exercises
To do
0 of 3 done today
4 of 7 days this week
[aria-label: 0 of 3 exercises done today]
Start today's exercises
Left shoulder
Week 1 · 2 exercises
Done for today
[aria-label: 2 of 2 exercises done today]
1 new message about this plan
AI
Ask about your exercises
Quick answers from your program. Your therapist can read these chats.
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

### 3b · Today at 768
plans left, visit and coach right
Monday 3 November
P-021
Good morning
Your plans
Right knee, post-op
Week 3 · Heel slides, Quad sets, Straight leg raises
To do
0 of 3 done today
4 of 7 days this week
[aria-label: 0 of 3 exercises done today]
Start today's exercises
Left shoulder
Week 1 · 2 exercises
Done for today
[aria-label: 2 of 2 exercises done today]
1 new message about this plan
Coming up
NOV
4
NEXT VISIT · TOMORROW
Tuesday, 9:00
45 minutes
Re-check range of motion
See all visits
AI
Exercise coach
Ask about your exercises
Quick answers from your program. Your therapist can read these chats.
Ask a question
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

## Visits, phone


### 4a · Visits list
next, cancelled, past
Visits
P-021
[aria-label: View]
List
Month
UPCOMING
TUE
4
9:00 · 45 min
Next
Re-check range of motion
Tomorrow
Ask to reschedule
TUE
11
9:00 · 45 min
Cancelled
Progress review
Cancelled by the clinic on 30 October
THU
13
10:30 · 45 min
Strength check
PAST
TUE
28
9:00 · 45 min
Past
Week 2 review
October
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

### 4b · Month view
shape and words, not colour alone
Visits
P-021
[aria-label: View]
List
Month
[aria-label: Previous month]
November
[aria-label: Next month]
[aria-label: November]
M
T
W
T
F
S
.
1
2
[aria-label: 3 November, today]
3
[aria-label: 4 November, visit at 9:00]
4
9:00
5
6
7
8
9
10
[aria-label: 11 November, visit cancelled]
11
Off
12
[aria-label: 13 November, visit at 10:30]
13
10:30
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
Visit
Cancelled
Today
TUE
4
9:00 · 45 min
Re-check range of motion
Ask to reschedule
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

### 4c · Ask to reschedule
sheet with a note
Visits
P-021
TUE
4
9:00 · 45 min
Re-check range of motion
Ask to reschedule
Tuesday 4 November, 9:00
Re-check range of motion · 45 minutes
Your clinic will reply with a new time. Your visit stays booked until then.
Anything we should know? (optional)
[placeholder: For example: mornings are hard this week.]
Send request
Keep this visit

### 4d · Request sent
visit stays booked
Visits
P-021
[aria-label: View]
List
Month
Request sent
Your clinic will reply in Messages. Your visit on Tuesday 4 November stays booked until they do.
UPCOMING
TUE
4
9:00 · 45 min
Re-check range of motion
Reschedule requested
You asked today at 08:15. Note: “Mornings are hard this week.”
TUE
11
9:00 · 45 min
Cancelled
Progress review
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

## Visits, tablet


### 4e · Visits at 768
month and list side by side
Visits
P-021
[aria-label: Previous month]
November
[aria-label: Next month]
[aria-label: November]
M
T
W
T
F
S
.
1
2
[aria-label: 3 November, today]
3
[aria-label: 4 November, visit at 9:00]
4
9:00
5
6
7
8
9
10
[aria-label: 11 November, visit cancelled]
11
Off
12
[aria-label: 13 November, visit at 10:30]
13
10:30
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
Visit
Cancelled
Today
UPCOMING
TUE
4
9:00 · 45 min
Next
Re-check range of motion
Ask to reschedule
TUE
11
9:00 · 45 min
Cancelled
Progress review
Cancelled by the clinic on 30 October
THU
13
10:30 · 45 min
Strength check
PAST
TUE
28
9:00 · 45 min
Past
Week 2 review · October
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

## Patient screens, larger text and higher contrast


### A1 · Messages
Larger text + Higher contrast
Messages
P-021
[aria-label: Plans of care]
Right knee, post-op
Left shoulder
1 new
Your therapist
How did the stairs feel this week?
You
Harder on Thursday, knee felt tight. Photo of the swelling attached.
Thursday 18:12 · Seen
This looks like a phone number or a name
Edit message
Send anyway
[aria-label: Add photo or PDF]
Message to your therapist
Call me on 615 555 0142
[aria-label: Send]
Not for emergencies. If you need help now, call 911.
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

### A2 · Coach answer and referral
Larger text + Higher contrast
Today
P-021
Ask about your exercises
AI
Answers come from an AI assistant using your exercise program. Your therapist can read this chat.
AI
AI assistant
Heel slides: 3 sets of 10.
Bend until you feel a gentle stretch.
You
My pain is worse. Should I stop?
That's one for your therapist
Worse pain, new symptoms, medicine and program changes need your therapist.
Message your therapist
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

### A3 · Emergency card
Larger text + Higher contrast
Today
P-021
Ask about your exercises
You
My calf is swollen and hot.
Please get help now
Call 911 or go to the nearest emergency room.
Call 911
Find the nearest emergency room
This is a set safety message from your clinic, not an AI answer.
[aria-label: Main]
Today
Progress
Messages
Visits
Settings

### A4 · Today
Larger text + Higher contrast
Monday 3 November
P-021
Good morning
NEXT VISIT · TOMORROW
Tuesday 4 November, 9:00
Re-check range of motion
To do
Right knee, post-op
0 of 3 done today
Start today's exercises
Done for today
Left shoulder
AI
Ask about your exercises
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

### A5 · Visits
Larger text + Higher contrast
Visits
P-021
[aria-label: View]
List
Month
Next
Tue 4 Nov, 9:00
Re-check range of motion
Ask to reschedule
Cancelled
Tue 11 Nov, 9:00
Progress review
Past
Tue 28 Oct, 9:00
Week 2 review
[aria-label: Main]
Today
Progress
Messages
1
unread
Visits
Settings

## Therapist inbox


### 5a · Inbox with an AI draft
st.sidebar, st.columns, st.dataframe, st.chat_message, st.text_area
Limber
Clinic workspace
[aria-label: Sections]
Inbox
4
Patients
Schedule
Settings
Find a patient
[placeholder: Patient code, for example P-021]
Inbox
Unread messages, grouped by plan of care
[aria-label: Conversations]
PATIENT
PLAN
UNREAD
P-021
Right knee, post-op
1
P-021
Left shoulder
0
P-034
Left hip
May need a direct response
2
P-008
Lower back
1
P-052
Right ankle
0
Select a row to open the conversation.
P-021 · Right knee, post-op
Started 3 weeks ago · Next visit Tuesday 4 November, 9:00
YOU
You · Wed 29 Oct, 10:14
How did the stairs feel this week?
P
P-021 · Thu 30 Oct, 18:12
Harder on Thursday, knee felt tight. Photo of the swelling attached.
[aria-label: Open photo: swelling, 30 October]
Swelling, 30 Oct
PDF
Surgeon letter.pdf · 240 KB
Draft a reply
Uses this conversation and P-021's program. Nothing is sent.
Reply to P-021
AI
AI-drafted — check before sending
Thanks for the photo. Some tightness after stairs is common at this stage, but your pain going from 3 to 6 this week is worth a closer look. Please keep going with heel slides and quad sets, and ice for 15 minutes afterwards. We will check your range of motion and the swelling on Tuesday. If your calf becomes swollen, hot or tender, call us or 911 straight away.
This draft is never sent on its own. Edit it, then press Send, or discard it.
Send
Discard draft

### 5b · Draft withheld
chest pain, a fall, numbness and similar
Limber
Clinic workspace
[aria-label: Sections]
Inbox
4
Patients
Schedule
Settings
Find a patient
[placeholder: Patient code, for example P-021]
Inbox
Unread messages, grouped by plan of care
[aria-label: Conversations]
PATIENT
PLAN
UNREAD
P-021
Right knee, post-op
0
P-021
Left shoulder
0
P-034
Left hip
May need a direct response
2
P-008
Lower back
1
P-052
Right ankle
0
P-034 · Left hip
Started 6 weeks ago · Next visit Thursday 6 November, 14:00
P
P-034 · Today, 07:52
I had a fall this morning getting out of bed.
P
P-034 · Today, 07:55
Now my left foot feels numb. Should I still do the exercises?
This message may need a direct response
P-034 mentioned a fall and numbness. The assistant has not drafted a reply. Please contact the patient directly.
Draft a reply
Drafting is off for this message.
Reply to P-034
[placeholder: Write your reply]
Send
Mark as handled by phone

## Weekly summary panel


### 6a · Patient page with the summary
st.tabs, st.metric, st.container(border=True), st.page_link
Limber
Clinic workspace
[aria-label: Sections]
Inbox
3
Patients
Schedule
Settings
P-021
Right knee, post-op · Started 3 weeks ago · Also: Left shoulder
[aria-label: Patient sections]
Overview
Exercises
Messages
Session notes
AI settings
Days done, last 7
4 of 7
Pain, latest
6/10
Up 3 from last week
Next visit
Tue 4 Nov, 9:00
Re-check range of motion
Weekly summary
27 October to 2 November · made today at 08:30 from 18 records
Summarise again
AI
AI-drafted — check before acting
Adherence
Exercises done on 4 of 7 days. Missed Thursday, Saturday and Sunday. Straight leg raises were skipped most often.
Exercise log · 7 entries
Pain trend
Pain rose from 3/10 to 6/10. The highest score was on Thursday 30 October, the day the patient said stairs felt harder.
Pain log · 6 entries
Questions asked
2 coach questions about heel slide depth and quad set holds, answered from the program. 1 coach question about worse pain was sent to you. 1 message with a swelling photo.
Coach chats · 3
Message · 30 Oct
Suggested next steps
Look at the swelling photo before Tuesday's visit.
From: Message · 30 Oct
Check range of motion and swelling on Tuesday before progressing the program.
From: Pain log
·
Exercise log
Ask about the missed days and whether straight leg raises hurt.
From: Exercise log
·
Coach chat · 1 Nov
Save as session note
Edit
Discard
P-021 never sees this summary.

### 6b · Summary panel states
idle, loading, saved, no records, unavailable
IDLE
Weekly summary
Summarise the last 7 days
Uses P-021's exercise log, pain log, messages and coach chats. Nothing is sent to the patient.
LOADING
Weekly summary
Summarise the last 7 days
Reading 7 days of records. This can take up to 20 seconds.
SAVED
Weekly summary
Saved as a session note
The note keeps the AI-drafted label until you edit and sign it.
Open session note
NO RECORDS THIS WEEK
Weekly summary
No records this week
P-021 has not logged exercises, pain or messages since 27 October. There is nothing to summarise.
Message P-021
ASSISTANT UNAVAILABLE
Weekly summary
The assistant isn't available right now
Your records are safe. Try again in a few minutes, or read the logs directly.
Try again
Open exercise log

## AI settings per patient


### 7a · AI settings for P-021
st.toggle, st.container, st.dataframe, st.expander
Limber
Clinic workspace
[aria-label: Sections]
Inbox
3
Patients
Schedule
Settings
P-021
Right knee, post-op · Started 3 weeks ago · Also: Left shoulder
[aria-label: Patient sections]
Overview
Exercises
Messages
Session notes
AI settings
Both are off for every new patient. Turn them on only after you have told the patient.
Weekly summaries and drafts
On since 13 October
Lets you make AI summaries of the last 7 days and AI-drafted replies in the inbox. Nothing reaches P-021 unless you send it.
WHAT P-021 IS SHOWN
Your therapist may use an AI assistant to summarise your week and to draft replies. Your therapist reads and checks everything before it reaches you.
Patient exercise coach
On since 13 October
P-021 can ask an AI assistant about their own program. It answers only from the program, sends worse pain, new symptoms, medicine and program changes to you, and shows a fixed emergency card for red flags.
WHAT P-021 IS SHOWN BEFORE THEIR FIRST QUESTION
Your therapist has turned on the exercise coach. It is an AI assistant that answers questions using your exercise program only. Your therapist can read these chats. It is not for emergencies.
Past coach conversations
Read only. Newest first.
[aria-label: Past coach conversations]
DATE
QUESTIONS
OUTCOME
Mon 3 Nov
1
Emergency card shown
Sat 1 Nov
2
1 sent to you
1 answered
Wed 29 Oct
1
Answered
Sat 1 Nov · 2 questions
P
P-021 · 09:01
How far should I bend in heel slides?
AI
AI assistant · 09:02
Heel slides: 3 sets of 10. Bend until you feel a gentle stretch, then slide your heel back out.
P
P-021 · 09:05
My knee pain is worse this week. Should I stop the leg raises?
SET
Set message · referral card
That's one for your therapist. P-021 was offered Message your therapist.
Mon 3 Nov · 1 question · emergency card
DEFAULT FOR A NEW PATIENT
[aria-label: Weekly summaries and drafts]
Weekly summaries and drafts · Off
[aria-label: Patient exercise coach]
Patient exercise coach · Off

## Therapist screens, larger text and higher contrast


### T1 · Inbox with draft
Larger text + Higher contrast
Limber
[aria-label: Sections]
Inbox
4
Patients
Schedule
Settings
Inbox
[aria-label: Conversations]
PATIENT
PLAN
UNREAD
P-021
Right knee, post-op
1
P-034
Left hip ·
May need a direct response
2
YOU
You · Wed 29 Oct
How did the stairs feel this week?
P
P-021 · Thu 30 Oct
Harder on Thursday, knee felt tight. Photo of the swelling attached.
[aria-label: Open photo: swelling, 30 October]
Swelling, 30 Oct
Draft a reply
AI
AI-drafted — check before sending
Reply to P-021
Thanks for the photo. Your pain going from 3 to 6 this week is worth a closer look. We will check the swelling on Tuesday. If your calf becomes swollen, hot or tender, call us or 911 straight away.
Send
Discard draft

### T2 · Weekly summary
Larger text + Higher contrast
Limber
[aria-label: Sections]
Inbox
3
Patients
Schedule
Settings
P-021
[aria-label: Patient sections]
Overview
Messages
AI settings
Weekly summary
AI
AI-drafted — check before acting
Adherence.
Done on 4 of 7 days.
Exercise log
Pain trend.
Rose from 3/10 to 6/10, highest on Thursday 30 October.
Pain log
Questions asked.
3 coach questions, 1 sent to you. 1 message with a photo.
Coach chats
Suggested next steps
Look at the swelling photo before Tuesday.
Message · 30 Oct
Check range of motion and swelling before progressing.
Pain log
Save as session note
Edit
Discard
The assistant isn't available right now
Try again in a few minutes.

### T3 · AI settings and withheld notice
Larger text + Higher contrast
Limber
[aria-label: Sections]
Inbox
3
Patients
Schedule
Settings
P-021
[aria-label: Patient sections]
Overview
Messages
AI settings
Weekly summaries and drafts · On
Nothing reaches P-021 unless you send it.
Your therapist may use an AI assistant to summarise your week and to draft replies. Your therapist reads and checks everything before it reaches you.
Patient exercise coach · Off
Off by default.
Your therapist has turned on the exercise coach. It is an AI assistant that answers questions using your exercise program only. Your therapist can read these chats. It is not for emergencies.
This message may need a direct response
P-034 mentioned a fall and numbness. No draft was made.
