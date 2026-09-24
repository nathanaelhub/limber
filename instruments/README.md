# Questionnaires

One YAML file per questionnaire. Drop a file in here and it can be assigned to a patient at once: no
code change, no restart. A file with a mistake in it is reported in the therapist's Patients page with
the file's name and the problem, and is skipped; the others keep working.

`demo_knee_function.yaml` is a worked example written for this project. **It is not a validated or
licensed clinical instrument**, and the app says so wherever its score appears. Real instruments are
licensed: obtain the licence, then write the instrument as its own file here, keeping its wording
exactly as licensed.

## The fields

| Field | What it is |
|-------|------------|
| `key` | Lower-case identifier, unique across files. Stored with every answer, so do not change it once answered. |
| `name` | What the patient and therapist see. |
| `meaning` | One plain sentence saying what the score means. Shown to both sides (constitution V). |
| `unit` | For example `points (0-40)` or `mean of 0-3`. |
| `direction` | `higher_is_better` or `higher_is_worse`. |
| `version` | Whole number. **Raise it whenever you change the items, choices, reversals, subscales, or scoring.** |
| `notice` | Optional. Anything the therapist must know, such as that the instrument is a demonstration. |
| `scoring` | `sum` or `mean` of the item values. |
| `missing` | `minimum_answered` (below it an answer set is refused) and `replace_with_mean` (whether the mean of the answered items stands in for a missing one). Left out, every item must be answered. |
| `choices` | The answers shared by the items: each `{text, value}`, at least two, values distinct. |
| `items` | Each `{key, text}`, optionally its own `choices` and `reversed: true`. |
| `subscales` | Optional `{key, name, items}`; scored the same way over their own items. |

A reversed item is turned round inside its own range (`minimum + maximum - value`), so an instrument
where pain is asked "how bad" can still total the same way round as the rest.

## Changing a file after patients have answered

Raise `version`. Stored answers keep the scores worked out at the time, along with a snapshot of the
rules that produced them, and the therapist's view says which version each score came from. Nothing is
ever rescored, so a change here cannot move a number a therapist has already seen.

## What an instrument may not do

- Ask for identifying details (a name, a date of birth, a record number, an address, a phone number, an
  email). Such an item is refused when the file is read.
- Carry branching or skip logic, free-text questions, or scoring bands. None of these exist yet.
