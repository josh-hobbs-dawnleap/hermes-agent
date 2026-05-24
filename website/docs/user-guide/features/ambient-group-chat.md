---
sidebar_position: 18
title: "Ambient Group Chat"
description: "Let Hermes observe trusted group chats, wake only when useful, and manage bounded social errands"
---

# Ambient Group Chat

Ambient group chat lets Hermes observe ordinary messages in explicitly allowlisted trusted group chats without replying to every message. A small classifier decides whether the full agent should wake, whether a low-risk memory candidate should be queued, or whether a bounded social errand should be created or triggered.

:::warning
Ambient mode is default-off and should only be enabled for trusted chats. Do not use it for email, web pages, documents, public channels, or any source where message text cannot authenticate the speaker.
:::

## What It Does

For Telegram groups, Hermes can:

- observe ordinary unmentioned messages in configured groups or topics;
- ignore most chatter without waking the main agent;
- wake the agent for direct questions, obviously useful help, or rare short quips, using a no-tools ambient turn for unmentioned chatter;
- detect conservative memory candidates about known people without replying;
- keep social errands such as one-shot relays or pending cue-triggered replies in a small auditable store.

The feature is designed for household or team-assistant use, for example:

- Josh asks Hermes to relay a message to Julia with attribution;
- Julia asks Hermes to respond later when a specific phrase appears in a trusted family group;
- Julia states a low-risk durable preference in a trusted chat and Hermes records it as `Julia ...`, not as vague `User ...`.

## Safety Model

Ambient chat deliberately separates three things:

1. **Identity mappings** — who a platform account belongs to.
2. **Social errands** — temporary cross-chat tasks with expiry and audit history.
3. **Persistent memory** — durable named-person facts only.

Rules:

- ambient mode only runs when `ambient.enabled: true` and the chat/topic is in the Telegram ambient allowlist;
- direct mentions and replies still use the normal Telegram trigger path;
- observed chat content is passed to the classifier as content, never as system or developer instructions;
- untrusted content cannot establish identity, write memory, or create errands;
- relays are attributed, not impersonated: `Josh Hobbs asked me to relay: "..."`;
- errands expire and default to one use;
- spontaneous non-addressed responses are cooldown-limited per chat/topic.

## Configuration

```yaml
ambient:
  enabled: false
  provider: ""
  model: ""
  max_context_messages: 12
  response_cooldown_seconds: 900
  memory_enabled: true
  memory_auto_save_low_sensitivity: false
  memory_confirm_sensitive: true
  social_errands_enabled: false

telegram:
  require_mention: true
  observe_unmentioned_group_messages: true
  group_allowed_chats:
    - "-1001234567890"
  ambient_chats:
    - "-1001234567890"
    - "-1001234567890:17585"  # optional topic-specific ambient gate
```

Environment equivalents:

```bash
HERMES_AMBIENT_ENABLED=true
HERMES_AMBIENT_PROVIDER=openrouter
HERMES_AMBIENT_MODEL=openai/gpt-4o-mini
HERMES_AMBIENT_MAX_CONTEXT_MESSAGES=12
HERMES_AMBIENT_RESPONSE_COOLDOWN_SECONDS=900
HERMES_AMBIENT_MEMORY_ENABLED=true
HERMES_AMBIENT_MEMORY_AUTO_SAVE_LOW_SENSITIVITY=false
HERMES_AMBIENT_MEMORY_CONFIRM_SENSITIVE=true
HERMES_AMBIENT_SOCIAL_ERRANDS_ENABLED=false
TELEGRAM_GROUP_ALLOWED_CHATS=-1001234567890
TELEGRAM_AMBIENT_CHATS=-1001234567890,-1001234567890:17585
```

:::tip
Use a cheap auxiliary model for the ambient classifier. The classifier receives a tiny context window and no tools, then returns JSON only. The full agent only wakes when the classifier says a response is worth it.
:::

## Telegram Requirements

Telegram bots cannot see normal group chatter unless Telegram privacy is disabled for the bot in BotFather and the bot has access to the group messages. Keep `require_mention: true` enabled so ordinary direct group participation still requires mention/reply unless ambient mode explicitly wakes the agent.

Ambient routing is a second gate on top of the existing group-observation gate. The chat must be permitted by `telegram.group_allowed_chats` (and any existing topic controls you use) before `telegram.ambient_chats` is considered. For topics, allowlist the specific `chat_id:thread_id` pair in `telegram.ambient_chats` when only one topic should be eligible for proactive ambient wakeups.

## Operator Commands

Identity mappings are stored outside profile memory so operators can inspect and edit them:

```bash
hermes identity list
hermes identity add telegram 123456789 "Julia Hobbs" --visible-name "Julia" --confidence explicit --approved-by "Josh Hobbs"
```

Social errands are inspectable and cancellable:

```bash
hermes errands list
hermes errands list --status pending
hermes errands cancel <errand-id> --actor "Josh Hobbs"
```

These commands operate on profile-local files under `HERMES_HOME`.

## Rollout Recommendation

Start small:

1. Enable Telegram only.
2. Use one trusted test group or one Telegram topic.
3. Use a cheap ambient classifier model.
4. Keep spontaneous responses capped with a cooldown of at least 15–30 minutes.
5. Populate identity mappings for the small set of people who may participate.
6. Review `hermes errands list` regularly during the first rollout.
7. Expand only after the logs show that Hermes is ignoring normal chatter and waking rarely.

## Live Telegram Rollout Checklist

Use this sequence when enabling a real group. It keeps side effects disabled until you have observed the classifier and identity mappings behaving correctly.

1. **Prepare a tiny test surface**
   - Create or choose one trusted Telegram test group/topic.
   - In BotFather, disable privacy for the bot so it can receive group chatter.
   - Add the bot to the group and confirm normal mention/reply behavior still works.

2. **Enable observation and classification only**
   ```yaml
   ambient:
     enabled: true
     provider: openrouter
     model: openai/gpt-4o-mini
     memory_enabled: true
     memory_auto_save_low_sensitivity: false
     memory_confirm_sensitive: true
     social_errands_enabled: false

   telegram:
     require_mention: true
     observe_unmentioned_group_messages: true
     group_allowed_chats:
       - "-1001234567890"
     ambient_chats:
       - "-1001234567890"
   ```
   Restart the gateway after editing config.

3. **Populate explicit identities**
   ```bash
   hermes identity add telegram 123456789 "Josh Hobbs" --visible-name "Josh" --confidence explicit --approved-by "Josh Hobbs"
   hermes identity add telegram 987654321 "Julia Hobbs" --visible-name "Julia" --confidence explicit --approved-by "Josh Hobbs"
   hermes identity list
   ```

4. **Observe without durable side effects**
   - Send ordinary chatter and confirm Hermes remains silent.
   - Send a clearly useful ambient prompt and confirm any wakeup is short and uses no tools.
   - Inspect gateway logs for ambient classifier decisions.
   - Inspect stores:
     ```bash
     hermes errands list
     hermes identity list
     ```

5. **Enable one higher-risk behaviour at a time**
   - Keep `memory_auto_save_low_sensitivity: false` until memory-candidate text has been reviewed manually.
   - Keep `social_errands_enabled: false` until target identity mappings and attribution policy are confirmed.
   - When enabling social errands, start with one mapped recipient and inspect `hermes errands list --status pending` frequently.

6. **Stop / rollback switch**
   ```yaml
   ambient:
     enabled: false

   telegram:
     observe_unmentioned_group_messages: false
     ambient_chats: []
   ```
   Restart the gateway. This returns Telegram groups to mention/reply-only behavior.

## Current Limitations

Ambient support is Telegram-first. The classifier/runtime gate can already wake the agent or stay silent for observed group messages; unmentioned ambient wakeups run as no-tools turns with an explicit prompt-injection boundary. Identity mappings, memory-candidate preparation, and social-errand stores/resolution are implemented as safe helper layers and operator controls, but automatic memory persistence and real platform delivery should remain disabled until the operator has reviewed the diff, populated trusted identity mappings, and chosen the final delivery policy.

Other gateway adapters can use the same identity, memory-candidate, and social-errand helpers later, but they need adapter-specific routing work before they observe group chatter safely.
