# Error Messages

Full detail for error messages in Step 2 of SKILL.md.

## The three things a good error message does

1. **States what happened**, in plain language, without technical jargon or internal system
   terms leaking through. "We couldn't save your changes" not "PUT /api/v2/documents/save
   returned 503."
2. **Explains why, when the reason is useful and knowable.** Not every error needs a reason (a
   generic network failure often doesn't have one worth stating), but when there is a specific,
   actionable reason, state it: "This file is too large (max 10MB)" is far more useful than
   "Upload failed."
3. **Says what to do next, when there's something the user can actually do.** "Try again in a
   few minutes" or "Check your internet connection" gives the user a next step. If there's
   genuinely nothing the user can do (a server-side outage, for example), don't invent a fake
   action, say so honestly and, if relevant, point to a status page or support contact instead.

## Never blame the user

Neutral framing describes the problem without implying fault:

- Not: "You entered an invalid email"
- Yes: "That email address doesn't look right"

The difference is subtle but real, the first frames the user as having made a mistake, the
second frames the situation as a fact to be corrected together. This matters even more for
errors that aren't actually the user's fault at all (a server error, a timeout), where blaming
language is not just unkind but factually wrong.

## Match severity of language to severity of the problem

A minor validation issue ("This field can't be empty") shouldn't use alarming language
("Critical error: field required"). Reserve strong language (words like "critical", "fatal",
"failed") for situations that actually warrant it, overusing severe language for minor issues
trains users to ignore it when something genuinely serious happens.

## Don't expose internals, but don't be so vague it's useless either

There's a middle ground between "PUT /api/v2/documents/save returned 503 Service Unavailable"
and "Something went wrong." Aim for language that's specific about the user-facing impact
without leaking implementation detail: "We couldn't save your changes, try again in a moment."
If an error code or reference ID is useful for support purposes, it's fine to include it, but
as a small secondary detail, not as the primary message the user reads first.

## Recoverable vs unrecoverable errors need different framing

- **Recoverable** (a form field is wrong, a temporary network blip): frame it as something to
  fix and retry, give the specific fix if known.
- **Unrecoverable in the moment** (a permissions issue, a resource that no longer exists): be
  honest that retrying won't help, and point toward the actual resolution path (contact an
  admin, request access, go back) instead of implying a retry button will fix it.

## Example set

| Situation | Weak | Better |
|---|---|---|
| Empty required field | "Error: field required" | "Enter your project name" |
| Wrong password | "Invalid credentials" | "That password doesn't match. Try again or reset it." |
| Network failure | "Something went wrong" | "We couldn't connect. Check your internet and try again." |
| File too large | "Upload failed" | "This file is too large. Max size is 10MB." |
| No permission | "Access denied" | "You don't have permission to view this. Ask an admin for access." |
| Server error | "Error 500" | "Something's wrong on our end, we're looking into it. Try again shortly." |
