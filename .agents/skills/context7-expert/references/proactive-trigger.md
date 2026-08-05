# Proactive Trigger and Confidence Threshold

Full detail for Step 0 in SKILL.md. This is the part the original Context7 rule files got
wrong: they described *what* the skill does but not *when to reach for it without being
asked*, which is why it kept requiring an explicit "use context7" instead of activating on
its own.

## Trigger even without the word "context7" or a direct question

Reach for this skill any time one of these is true, whether or not the user names Context7 or
even names a library explicitly:

- The user asks a setup, configuration, "how do I", or API signature question that names a
  library, framework, SDK, CLI tool, or cloud service, however casually phrased.
- You're about to write, generate, or fix code that calls into a specific library's API, and
  you're not fully certain the method names, signatures, or config shape you're about to use
  are still current for that library's latest (or user-specified) version.
- The user mentions a specific version of something ("Next.js 15", "React 19", "Prisma 6").
- The user pastes an error message or stack trace that clearly originates from a specific
  library and the fix depends on that library's current behavior, not just general debugging
  logic.
- You catch yourself about to answer from memory about a library's API and would have said
  "I believe" or "as of my training" or something similarly hedged, that hedge is itself the
  trigger, look it up instead of stating the hedge.

## The confidence threshold

Training data confidence has to be genuinely certain, not just familiar, to skip this skill.
"I've seen this library many times" is not the same as "I'm certain this exact API surface is
unchanged in the current version." Default to checking. The cost of an unnecessary lookup is
low (a few seconds), the cost of a confidently wrong API signature in generated code is much
higher (a broken build, or worse, code that runs but does the wrong thing).

Exceptions where training data alone is fine, no need to trigger:

- Timeless language or framework concepts that don't change with library versions (what a
  closure is, what REST means, general algorithmic complexity)
- The user is asking about something with no external library involved at all
- The task is refactoring, code review, or business logic debugging where no specific
  library API is actually in question, see the "Do not use for" list in SKILL.md's
  description

## Don't narrate it

Once triggered, just call the tool or run the command, don't announce "I'm going to check
Context7 for this" as a separate sentence before doing it. Weave the lookup into normal
work the way a developer would reach for documentation without narrating the reach.
