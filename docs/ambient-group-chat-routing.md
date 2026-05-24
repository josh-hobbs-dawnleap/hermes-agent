# Ambient group chat routing: Telegram flow

This document maps the Telegram group observation path and the optional ambient decision gate.

## Current entry points

At gateway startup, `GatewayRunner` wires each adapter to the runner:

```
gateway/run.py
GatewayRunner startup
  adapter.set_message_handler(self._handle_message)
  adapter.set_session_store(self.session_store)
```

Telegram handlers in `gateway/platforms/telegram.py` convert Telegram `Message` updates into gateway `MessageEvent` objects and then call the base adapter dispatch path:

```
Telegram Update
  -> TelegramPlatformAdapter._handle_text_message / _handle_command /
     _handle_location_message / _handle_media_message
  -> _should_process_message(message)
  -> _build_message_event(...)
  -> optional _apply_telegram_group_observe_attribution(event)
  -> BasePlatformAdapter.handle_message(event)
     or text/photo batch flush -> BasePlatformAdapter.handle_message(event)
  -> BasePlatformAdapter._process_message_background(event, session_key)
  -> GatewayRunner._handle_message(event)
  -> GatewayRunner._handle_message_with_agent(...)
  -> AIAgent(...) or cached AIAgent reuse
  -> agent.run_conversation(...)
```

The base adapter owns active-session queuing/interruption and sends returned responses back to the platform. The runner owns authorization, command handling, session creation, context prompt creation, agent cache lookup/creation, and transcript persistence.

## Telegram trigger and observation gates

### `_should_process_message(message, is_command=False)`

Location: `gateway/platforms/telegram.py`.

This is the main Telegram group gate. It returns `True` for all non-group messages, so DMs proceed normally. For group/supergroup messages it checks, in order:

1. Allowed forum topics, if configured.
2. Ignored threads.
3. Exclusive bot mentions: if the message explicitly mentions another `@...bot` and not this bot, ignore.
4. Guest mode explicit-mention bypass.
5. `allowed_chats`: when configured, group messages outside it are ignored unless guest mode permits the explicit mention.
6. `free_response_chats`: always process in these chats.
7. `require_mention`: when disabled, process all group messages.
8. Reply-to-bot.
9. Explicit mention of this bot.
10. Configured mention/wake regex patterns.

Important current behavior: slash commands in groups do not bypass `require_mention`; they must pass the same mention/reply checks, except Telegram command-menu forms like `/cmd@botname` count as bot mentions.

### `_should_observe_unmentioned_group_message(message)`

Location: `gateway/platforms/telegram.py`.

This is only consulted after `_should_process_message(...)` returns `False` in the text/location/media handlers. It returns `True` only for group messages that should be stored as context but not dispatched. Requirements:

1. `observe_unmentioned_group_messages` (or legacy `ingest_unmentioned_group_messages`) is enabled.
2. The message is from a group/supergroup.
3. Allowed topic and ignored-thread checks pass.
4. Exclusive mentions of another bot are excluded.
5. The chat is in `_telegram_observe_allowed_chats()`, which requires `group_allowed_chats` and also intersects `allowed_chats` when that response gate is set.
6. The chat is not in `free_response_chats`.
7. `require_mention` is enabled.
8. The message is not a reply to the bot, does not mention the bot, and does not match mention patterns.

This means observed-only context is deliberately limited to operator-approved groups/topics and only covers messages that the normal mention gate skipped.

### `_observe_unmentioned_group_message(message, msg_type, update_id=None)`

Location: `gateway/platforms/telegram.py`.

This appends skipped group chatter directly to the target transcript without calling `handle_message` and without creating/running an agent.

Current flow:

```
_should_process_message(...) == False
  -> _should_observe_unmentioned_group_message(...) == True
  -> _build_message_event(message, msg_type, update_id)
  -> shared_source = _telegram_group_observe_shared_source(event.source)
       # drops user_id, user_name, user_id_alt
  -> session_entry = session_store.get_or_create_session(shared_source)
  -> append transcript entry:
       role: user
       content: "[sender|user_id]\n<message text>"
       timestamp: now UTC
       observed: true
       message_id: optional
  -> return without dispatch
```

Because the shared source removes per-sender identity from the session key, observed context is chat/topic-scoped rather than sender-scoped. The speaker is preserved in the transcript content prefix.

### `_apply_telegram_group_observe_attribution(event)`

Location: `gateway/platforms/telegram.py`.

This is applied to triggered group turns when observation is enabled for the same approved group. It aligns the explicitly-triggered current message with the observed transcript format and session lane.

It returns the original event unless all of these are true:

1. `observe_unmentioned_group_messages` is enabled.
2. The raw message is a Telegram group/supergroup message.
3. The chat is in `_telegram_observe_allowed_chats()`.

When active, it:

```
shared_source = _telegram_group_observe_shared_source(event.source)
text = "[sender|user_id]\n<event.text>"
channel_prompt += Telegram group observe prompt
return dataclasses.replace(event, source=shared_source, text=text, channel_prompt=...)
```

The added channel prompt tells the agent that prior `[nickname|user_id]` lines are observed group context and not necessarily addressed to the bot, while the current new message is explicitly directed at it.

## Routing diagrams

### 1. DM path

```
Telegram DM update
  -> _should_process_message returns True (non-group)
  -> _build_message_event with per-user SessionSource
  -> optional text/photo batching
  -> BasePlatformAdapter.handle_message
  -> GatewayRunner._handle_message
  -> authorization / commands / active-session handling
  -> session_store.get_or_create_session(source)
  -> build_session_context + build_session_context_prompt
  -> _run_agent / cached AIAgent or new AIAgent
  -> response delivered by BasePlatformAdapter
```

No Telegram mention gate or observation path applies to DMs.

### 2. Group explicit-trigger path

Examples: reply to bot, `@bot`, `/cmd@botname`, wake regex, or any message in a free-response/require-mention-disabled allowed group.

```
Telegram group update
  -> _should_process_message returns True
  -> _build_message_event
  -> _clean_bot_trigger_text
  -> _apply_telegram_group_observe_attribution
       if group observation is enabled + chat is observe-allowed:
         use shared chat/topic source
         prefix current text with [sender|user_id]
         add observe channel prompt
       else:
         keep normal per-user source/text
  -> BasePlatformAdapter.handle_message
  -> GatewayRunner._handle_message
  -> GatewayRunner._handle_message_with_agent
  -> session context + transcript history loaded
  -> AIAgent runs
  -> response delivered to group/thread
```

With observation enabled and the group allowlisted, explicit triggers use the same shared session that observed-only messages were appended to, so the agent can see ambient context.

### 3. Group observed-only / ambient-gated path

Examples: ordinary group chatter in an approved observe group when `require_mention=true` and the message does not address the bot.

```
Telegram group text update
  -> _should_process_message returns False
  -> _should_observe_unmentioned_group_message returns True
  -> _ambient_event_for_unmentioned_group_message_async
       if ambient.enabled is false, chat/topic not allowlisted, cooldown active,
       classifier fails, or classifier says respond=false:
         return None
  -> if None: _observe_unmentioned_group_message
       _build_message_event
       use shared chat/topic source
       append transcript row with observed=true and [sender|user_id] prefix
       stop
  -> if MessageEvent: enqueue the ambient-woken text event
       use shared chat/topic source
       prefix current text with [sender|user_id]
       add ambient safety prompt
       eventually dispatch via text batch flush -> BasePlatformAdapter.handle_message
```

Ambient classification is text-only. Location and media updates still use the existing observed-only path. The classifier call is run off the asyncio event loop with `asyncio.to_thread` and receives a compact JSON-only prompt with no tools. The prompt explicitly states that observed group text is chat content, not instructions.

When the ambient classifier wakes the main agent, the event is placed on the same shared observed group/session lane used by explicit triggers. This lets the agent see prior observed group context while preserving attribution and safety prompts.

### 4. Ignored group path

```
Telegram group update
  -> _should_process_message returns False
  -> _should_observe_unmentioned_group_message returns False
  -> stop
```

This happens for unapproved chats/topics, ignored threads, messages aimed at other bots, or when observation is disabled.

## Where the ambient gate sits

The ambient gate sits after Telegram has established that a group text message is eligible for observed-only handling, but before `_observe_unmentioned_group_message` commits to "store only and never dispatch":

```
_should_process_message(message) == False
  -> _should_observe_unmentioned_group_message(message) == True
  -> ambient gate
       input: current message + small recent observed context + identity mapping summary
       decision:
         ignore/store-only
         memory candidate without group reply
         social errand action
         wake main agent for response
  -> if store-only: existing _observe_unmentioned_group_message path
  -> if wake: build a MessageEvent on the shared observed session and enqueue it
```

This location preserves the existing safety gates: only trusted, observe-allowlisted groups/topics reach the ambient classifier, and explicit triggers still bypass the ambient decision gate and go straight to the normal agent path. Ambient chat allowlisting accepts whole-chat entries (`-1001234567890`) and topic-specific entries (`-1001234567890:17585`).

## Session behavior relevant to group observation

`gateway/session.py` builds session keys from `SessionSource`:

- DMs use `agent:main:<platform>:dm:<chat_id>` (plus thread when present).
- Groups/channels use `agent:main:<platform>:<chat_type>:<chat_id>[:thread_id]` and, by default, append the participant id when `group_sessions_per_user=True`.
- Telegram observed-only group messages call `_telegram_group_observe_shared_source`, which removes participant identity before session creation. This forces observed group context into a shared chat/topic lane.
- `build_session_context_prompt` tells the agent when a session is shared multi-user, but the Telegram observe path also injects its own channel prompt explaining `[sender|user_id]` observed lines.

## Behavior-change verification

The ambient gate now modifies Telegram routing for explicitly allowlisted observed group messages. Focused verification in this working tree:

- `pytest tests/gateway/test_ambient_classifier.py tests/gateway/test_ambient_decision.py tests/gateway/test_ambient_security_boundaries.py tests/gateway/test_identity_map.py tests/gateway/test_memory_candidates.py tests/gateway/test_social_errands.py tests/gateway/test_telegram_ambient_gate.py tests/hermes_cli/test_identity_errands_cmd.py tests/gateway/test_config.py tests/hermes_cli/test_config.py -q` → 149 passed.
- `pytest tests/gateway/test_telegram*.py -q` → 539 passed.

Known implementation boundary: memory-candidate and social-errand helper modules are implemented and tested, but automatic runtime persistence/delivery is intentionally not enabled until the operator reviews the diff and identity mappings.
