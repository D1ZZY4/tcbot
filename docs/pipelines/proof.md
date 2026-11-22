# Proof: media collection, debounce, upload, and archive

This document describes the proof pipeline shared by ban, kick, mute, and warn: the accepted media shapes, album debounce and the 60 second cap, the Done and timer flush claim, the upload to `PROOFS`, landed items, partial galleries, and the archive written with the decision. The shared spine is in [banning.md](banning.md).

## 1. Accepted media

`PROOF_MEDIA_FILTER` in `proof_flow.py` is the single owner of which message shapes count as evidence:

```python
PROOF_MEDIA_FILTER = (
    filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.Document.ALL
)
```

Photos, videos, animations, and documents are accepted. Voice notes, video notes, and stickers are rejected. Every proof receiver and every unexpected-type handler uses the same filter, so the two cannot drift apart within a flow or across flows.

`BuildProof(action, skip_allowed=...)` owns the proof-step keyboard through `buttons.proof_step_btn()`:

| Callback data | Meaning |
|---|---|
| `<action>_skip_proof` | Execute without proof, when allowed |
| `<action>_done_proof` | Flush collected proof and execute |
| `<action>_cancel` | Cancel the flow |

The ban path uses `BuildProof("ban", skip_allowed=False)`, so proof is mandatory there. Kick, mute, and warn use the default `skip_allowed=True`.

## 2. Two collection models

```mermaid
flowchart TD
    START[Proof prompt shown] --> KIND{which flow family}
    KIND -->|ban| SESS[ban_flow ProofSession registry]
    KIND -->|kick mute warn| SCOPE[reason_flow scope buffer]
    SESS --> KEY[key is chat_id and user_id]
    SCOPE --> BUF[key is action_proof_msgs in flow scope]
    SESS --> DEB[debounce then hard 60 second cap]
    SCOPE --> DONE[Done or Skip claims action_executing flag]
    DEB --> EXEC[execute the moderation action]
    DONE --> EXEC
```

The ban flow needs a timed auto-flush because it forbids Skip and must not hang on an abandoned proof. `ProofSession` in `proof_session.py` holds the messages, a meta snapshot of the conversation scope, the deadline, the last arrival, and the flush task. The other flows use the `_ProofStepMixin` in `reason_flow.py`, which buffers media into scope and waits for an explicit Done or Skip.

## 3. Debounce and flush claim

```mermaid
sequenceDiagram
    participant Mod as Moderator
    participant Flow as ban_flow
    participant Reg as ProofSessionRegistry
    participant Timer as flush task
    Mod->>Flow: media message arrives
    Flow->>Reg: create session on first arrival with deadline now plus 60 seconds
    Flow->>Timer: schedule _flush_session
    Mod->>Flow: another media message
    Flow->>Reg: update last_arrival
    Mod->>Flow: ban_done_proof tap
    Flow->>Reg: set flushing flag synchronously
    Flow->>Timer: cancel the timer and await its finally block
    Timer-->>Flow: registry entry removed for that session
    Flow->>Flow: recheck rank then _execute_ban
```

`_flush_session()` loops in slices bounded by the smaller of `cfg.album_debounce` and the remaining time, and breaks on silence or the hard cap. The hard cap is `_PROOF_COLLECT_MAX_S = 60.0`, so a very large debounce value cannot leave a ban unflushed indefinitely. Setting `flushing` is a synchronous claim, so Done and the timer can never execute the same session. The `finally` block removes the registry entry only when it still holds the same session and clears that conversation's ban keys, so a successor session keeps its own entry.

`drain_proof_sessions()` is called at shutdown. It waits for running flushes up to 30 seconds, then cancels those still waiting. A running flush already owns its decision and fan-out, so it is never cancelled mid-execution.

## 4. Upload to `PROOFS`

```mermaid
flowchart TD
    MSG[collected source messages] --> CLASS[_source_media classification]
    CLASS --> NONE{any supported media}
    NONE -->|no| EMPTY[return empty ProofUpload]
    NONE -->|yes| SPLIT[split into gallery and singles]
    SPLIT --> GAL[photos and videos in media groups of at most 10]
    SPLIT --> SING[animations and documents sent individually]
    GAL --> CAP[caption on first item of first chunk only]
    CAP --> LAND[record landed items in send order]
    SING --> LAND
    LAND --> COUNT[expected_item_count counts every source attempted]
    COUNT --> UP[ProofUpload with first id link items and expected count]
```

`upload_proof_items()` groups photos and videos into one or more `send_media_group` calls, capped at ten items per group because Telegram rejects larger albums. Animations and documents cannot join a media group, so each is sent on its own. A failed gallery chunk is logged and skipped; a failed single is logged and skipped so one bad file cannot void a good gallery.

`ProofItem` records the landed message id, media type, item order, source chat and message ids, and the media metadata. `to_document()` converts it to the `EvidenceItemDoc` shape stored in the archive. `ProofUpload.landed` is true when at least one message reached the channel, and `documents()` returns every landed item.

A failed upload returns an empty `ProofUpload` instead of raising, because the moderation action is the important side effect. The ban executor checks `landed` itself.

## 5. Partial galleries and the ban proof requirement

```mermaid
flowchart TD
    UP[ProofUpload] --> PARTIAL{"len items < expected_item_count"}
    PARTIAL -->|yes| INCOMPLETE[partial batch recorded honestly]
    PARTIAL -->|no| FULL[complete batch]
    INCOMPLETE --> MODE{new ban or re-ban}
    FULL --> MODE
    MODE -->|new ban| ABORT[abort ban and edit prompt with proof failure]
    MODE -->|re-ban| CARRY[read previous evidence batch and carry it forward]
```

The ban executor aborts a new ban when the gallery is partial or nothing landed, so `/check` and the audit log never reference evidence that never arrived. A re-ban may keep the previous proof; `update_ban()` then reads the entire prior evidence batch, not just its first message, so media types and item counts stay accurate. Kick, mute, and warn treat proof as optional and simply attach whatever landed.

## 6. Archive and landed items

`moderation_db.archive_proof()` writes the upload row and its items inside the decision transaction. The same transaction opens the case, writes the `moderation_actions` decision, links the selected rules, and closes the case. Either the decision and its proof both commit, or neither does.

| Helper | Owner | Role |
|---|---|---|
| `PROOF_MEDIA_FILTER` | `proof_flow.py` | Accepted media shapes |
| `BuildProof` | `proof_flow.py` | Keyboard and prompts |
| `proof_step_btn` | `buttons/flows.py` | Skip, Done, Cancel callbacks |
| `upload_proof_media` | `proof_flow.py` | Upload owner and `ProofUpload` |
| `upload_proof_items` | `proof_flow.py` | Gallery chunking and singles |
| `ProofSession` and `proof_sessions` | `proof_session.py` | Ban session storage and drain |
| `_flush_session` | `ban_flow.py` | Debounce timer and claim |
| `demote_before_enforcement` | `demote_flow.py` | Runs after proof before enforcement |
| `archive_proof` | `moderation_db.py` | Durable evidence rows |

The proof caption is built by `messages.proof_caption_new()` for new decisions and `messages.proof_caption_update()` for re-bans, where it carries the previous proof link.

## 7. Continue reading

- [banning.md](banning.md): the full ban flow and where proof fits in enforcement.
- [unbanning.md](unbanning.md): lifting a ban that carries proof.
- [kicking.md](kicking.md): optional proof for a group kick.
- [muting.md](muting.md): optional proof for a timed mute.
- [warning.md](warning.md): optional proof for a filed warning.
