# Limber: components, states and tokens

## Tokens

Existing, unchanged: `--teal` #0E6B64, `--teal-dark` #0A544E, `--coral` #F2684A, `--ink` #16302C, `--muted` #728280, `--bg` #FAF8F4, `--card` #FFFFFF, `--line` #EDEAE2, `--warn` #B4432B.

New tokens, and why each is needed:

| Token | Value | Why |
|---|---|---|
| `--muted-text` | #5E6E6C | `--muted` is 3.8:1 on `--bg`, which fails AA for small text. This is 5.1:1. `--muted` stays for icons. |
| `--line-strong` | #D6D1C5 | Input, chip and button edges that older eyes can find. |
| `--teal-tint` | #E3EFED | Selected state, AI banner, referral card. |
| `--coral-tint` | #FDEBE5 | To do badge surface. |
| `--warn-tint` | #FBECE8 | Privacy warning, cancelled badge. |
| `--scrim` | ink at 48% | Behind sheets. |
| `--badge-bg` / `--badge-fg` | coral / ink | Unread counts. Ink on coral is 4.6:1. White on coral fails, so never use it. |
| `--bw` | 1px (2px in Higher contrast) | Border width. |
| `--r-card` / `--r-ctl` | 22px / 14px | Card and control radius. |
| `--fs-xs` to `--fs-h1` | 13 / 15 / 17 / 19 / 22 / 28 | Type scale. Larger text: 16 / 18 / 21 / 23 / 26 / 32. |

Higher contrast (`.hc`) swaps: teal becomes #0A544E (8.8:1), muted text becomes ink, lines become 2px ink, tints become white, badges become ink with white text, warn becomes #8E3220. Larger text is `.lt`. Less motion is `.lm` or the OS setting.

## Patient components

| Component | States |
|---|---|
| Plan switcher (chips at 390, list at 768) | Active plan; other plan with “N new”; no unread; past plan with archive icon and “ended”. Wraps to two rows in Larger text. |
| Message bubble | From therapist; from you; with photos; with PDF; sending; sent with time and “Seen”; failed with Try again. |
| Attachment tray | Empty; 1 to 4 photos with “N of 4 photos”; 4 of 4 (add disabled, says why); 1 PDF (add disabled, “One PDF per message”); uploading; remove button on every item (44px target). |
| Add menu sheet | Take a photo (phones only); Choose photos; Choose a PDF; Cancel. |
| Compose box | Empty (send disabled); typing; privacy warning; sending. Not shown for past plans or when the coach limit is reached. |
| Emergency note | One line above or below compose: “Not for emergencies. If you need help now, call 911.” |
| Privacy warning | Phone number found; name found. Actions: Edit message, Send anyway. Field gets a 2px warn border. |
| Past plan panel | Replaces the compose box. Explains why and links to the active plan. |
| AI label | Answer label “AI assistant”; chat banner; “AI-drafted — check before sending”; “AI-drafted — check before acting”. Always the boxed AI mark plus words. |
| Coach answer | Thinking (dots plus “Checking your program”, dots stop with Less motion); answer with bold exercise and dose; source link “From your program: …”. |
| Referral card | Default; after tap, the question is copied into a new message. Says “This is a set message from your clinic.” |
| Emergency card | One state only. Replaces any AI text. Call 911 (tel link) and Find the nearest emergency room. Says it is not an AI answer. |
| Coach unavailable | Turned off; daily limit reached; cannot connect. Each has Go to Messages. |
| Plan card | To do; in progress (N of M); done for today; new message link. |
| Coach entry | Card on Today, slim row at the top of Messages. |
| Next visit card | Tomorrow; later date; none booked. |
| Appointment row | Next; upcoming; reschedule requested; cancelled (struck through plus “Cancelled” badge); past (“Past” badge). |
| Month day | Plain; today (ring); visit (filled plus time); cancelled (dashed, struck, “Off”); past (muted). |
| Reschedule sheet | Open; sending; request sent (status card plus badge on the row). |
| Navigation bar | Today, Progress, Messages, Visits (new), Settings. Unread dot carries a number. |

## Therapist components (Streamlit)

| Component | Streamlit part | States |
|---|---|---|
| Section nav | `st.sidebar` with `st.page_link` | Current page; unread count. |
| Inbox list | `st.dataframe` with row selection | Unread; read; “May need a direct response”. |
| Conversation | `st.chat_message` | Therapist; patient; with `st.image` thumbnails; with PDF `st.download_button`. |
| Draft a reply | `st.button` then `st.text_area` | Idle; drafting (`st.spinner`); draft in box with AI label; edited; sent; discarded. Never sends by itself. |
| Withheld notice | `st.warning` | Shown when the patient mentions chest pain, a fall, numbness and similar. Draft button disabled. |
| Weekly summary | `st.container(border=True)`, `st.columns`, `st.page_link` | Idle; loading; result; saved; no records this week; assistant unavailable. |
| Patient metrics | `st.metric` in `st.columns` | Days done; pain with change; next visit. |
| AI switch | `st.toggle` plus `st.caption` and a quoted notice | Off (default); on with date. |
| Coach log | `st.dataframe` plus `st.expander` | Answered; sent to you; emergency card shown. |

Theme for Streamlit (`.streamlit/config.toml`): primaryColor #0E6B64, backgroundColor #FAF8F4, secondaryBackgroundColor #F1EEE7, textColor #16302C, font Sora. Corner radius 14px if your Streamlit version supports `baseRadius`.
