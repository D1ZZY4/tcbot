# Language and Vocabulary Verification

Full detail for Step 3 in SKILL.md. This is the most important addition to this skill: no
single training corpus is a complete, authoritative dictionary for any language, including
English, and definitely not for languages with smaller digital footprints in training data.
Guessing at correctness from a feel for the language is not the same as checking, and UI copy
is exactly the kind of text where a wrong word choice, a misspelling, or an unnatural
construction gets seen by every single user, repeatedly, forever.

## The general principle

When writing or auditing copy in any language, and the word choice, spelling, idiom, register,
or grammatical construction is anything less than fully certain, look it up against an actual
authoritative source for that specific language rather than proceeding on instinct. "Fully
certain" means genuinely certain, not just familiar-sounding, the same confidence bar used
elsewhere for factual claims. This is especially true for:

- Loanwords and borrowed terms (tech terminology borrowed into a language often has a
  specific, sometimes non-obvious, correctly absorbed spelling)
- Formal vs informal register distinctions that don't exist the same way in every language
- Regional spelling or usage variants
- Idiomatic phrasing that a literal translation would get wrong
- Any word that could plausibly have more than one accepted spelling

## Indonesian (Bahasa Indonesia)

The authoritative source is **KBBI** (Kamus Besar Bahasa Indonesia), maintained by Badan
Bahasa (Indonesia's national language authority, under Kemdikbud). This is not optional
background knowledge, general familiarity with Indonesian is not the same as verified
correctness against KBBI, since the language has absorbed loanwords, undergone spelling reform
(EYD, now EYD Edisi V), and has specific rules around affixation (imbuhan) that are easy to
get subtly wrong.

- Official online dictionary: `kbbi.kemdikbud.go.id`. Search for the specific word or phrase
  in question, don't assume based on how it's commonly written informally, since informal and
  spoken usage frequently diverges from the standardized correct form.
- For spelling and punctuation rules more broadly (not just individual word entries),
  Indonesia's spelling standard is EYD Edisi V (Ejaan yang Disempurnakan, current edition),
  also published by Badan Bahasa.
- Common trap: loanwords from English are often spelled differently once absorbed into formal
  Indonesian (for example, "sistem" not "system", "aktivitas" not "activitas"), verify these
  rather than keeping the English spelling or guessing at the absorbed form.
- Common trap: prefix/suffix combinations (imbuhan) can change a root word's spelling in ways
  that aren't always intuitive, check the full inflected form in KBBI, not just the root.
- For UI copy specifically, formal written Indonesian (bahasa baku) is usually the right
  register even when the product's overall voice is casual, check the project's own voice
  guide (`project-source-of-truth.md`) for whether informal Indonesian is intentionally used.

## English

Even for English, don't treat fluency as the same thing as verified correctness for anything
genuinely uncertain, spelling variants (American vs British), less common words, and newer
terminology all have edge cases worth checking.

- A proper dictionary (Merriam-Webster for American English, Oxford for British English) is
  the authority, not a general web search result or an encyclopedia entry.
- Check which variant (American vs British spelling) the project already uses elsewhere before
  introducing new copy, consistency within one product matters more than which variant is
  "more correct" in the abstract.

## Other languages

The same principle applies regardless of which language is in play: identify the actual
authoritative source for that language, not just any website that happens to come up.

- If uncertain which source is authoritative for a given language, search for it directly
  (for example, "official dictionary [language name]" or "[language name] language academy"),
  most languages with an official standardizing body have one: Real Academia Española for
  Spanish, the Académie Française and associated dictionaries for French, the Duden for
  German, and so on. Use the actual national or academic authority when one exists.
- If no single official body exists for a language, prefer a well-established, widely
  recognized dictionary for that language over a general web search snippet or a
  crowd-edited source.

## Wikipedia and general web sources: supplementary, not authoritative for language itself

Wikipedia and general reference sites are useful for confirming facts, terminology in a
specific technical domain, or how a proper noun is conventionally written, but they are
encyclopedias, not dictionaries, and are not the right source for verifying spelling, grammar,
or standard word choice. Use them to supplement, for example checking how a company or product
name is conventionally styled, but defer to the actual language authority (KBBI, a proper
dictionary, a national language academy) for anything about the language itself.

## If authoritative lookup is unavailable

Do not present uncertain wording as verified. Use this fallback order:

1. The project's approved terminology and existing product copy.
2. A trusted local dictionary or language resource already available in the environment.
3. A clearly labeled best-effort suggestion with the uncertain term or construction flagged.

Report that authoritative verification was not available and ask for review when the wording
affects legal meaning, safety, accessibility, localization quality, or a high-visibility
surface. Never invent a citation or imply that a source was consulted when it was not.

## How to actually do this in practice

Use an available authoritative lookup mechanism rather than answering from memory when verification
is warranted. This can be an approved web search or fetch tool, a dictionary database, or a
trusted language resource already available in the environment. Search for the specific word or
construction plus the authority's name, such as "sistem KBBI" or "loanword spelling KBBI", rather
than relying on a generic result. This is a normal, expected part of writing or auditing copy in
any language other than pure, common-knowledge English, not an extra step to skip for speed.
Getting a single word wrong in shipped UI copy is a visible, repeated, permanent mistake in a way
that few other kinds of errors are.
