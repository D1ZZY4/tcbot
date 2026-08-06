# Accessibility and Localization

Use this reference when copy appears in an accessible control, a status announcement, or a
product that may be translated.

## Accessible UI copy

- Give every interactive control a specific accessible name. Do not rely on an icon or color
  alone.
- Keep visible labels, accessible names, tooltips, and keyboard instructions consistent unless
  there is a clear usability reason to differ.
- Write validation errors next to the affected field and include a concise summary when several
  fields need attention.
- Make status messages understandable when read out of context by a screen reader. Include the
  result and, when useful, the next action.
- Do not encode meaning only through color, position, capitalization, or punctuation.

## Localization-ready copy

- Avoid concatenating fragments that depend on English word order.
- Keep variables named and documented, for example `{count} invoices`, and give translators
  enough context to place them naturally.
- Expect plural, gender, politeness, and grammatical agreement to vary by language. Use the
  project's localization framework rather than hand-built singular/plural rules.
- Avoid idioms, unexplained abbreviations, and jokes in messages that must be translated.
- Allow room for text expansion and do not bake dates, numbers, currencies, or units into prose.
  Use the product's locale-aware formatting utilities.
- Check right-to-left layouts when the target language requires them.

If localization or accessibility conventions already exist in the project, follow those
conventions over these portable defaults.