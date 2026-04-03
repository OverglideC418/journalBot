# Journal Bot

A shareable Discord journaling bot you can clone, configure, and run for yourself or a few friends. It posts nightly journaling prompts into a private Discord channel, lets each user answer by replying to specific prompt messages, and compiles the completed entry in question order when `!done` is used.

## Features

- Daily scheduled journaling per user
- Private-channel-first flow for reliable delivery
- One Discord message per question
- Reply-based answer mapping
- Partial completion with `!done`
- Text stats for the last week or month
- JSON-backed local storage with a clean path toward later network-folder storage
- GitHub-friendly setup with sample config and secret-free tracked files

## Project Layout

```text
journalBot/
├── config/
│   ├── prompts.example.json
│   └── settings.example.json
├── data/
│   ├── journals/
│   └── runtime/
├── journal_bot/
│   ├── bot.py
│   ├── config.py
│   ├── formatter.py
│   ├── models.py
│   ├── scheduler.py
│   └── storage.py
├── .env.example
├── .gitignore
├── main.py
├── README.md
└── requirements.txt
```

## Setup

1. Create a Discord application and bot at the Discord Developer Portal.
2. Enable the `MESSAGE CONTENT INTENT` for the bot.
3. Invite the bot to your server with permission to:
   - Read messages
   - Send messages
   - Read message history
   - Add reactions
4. Create a private text channel for journaling.
5. Copy the sample files:

```bash
cp .env.example .env
cp config/settings.example.json config/settings.json
cp config/prompts.example.json config/prompts.json
```

6. Edit `.env` and add your bot token.
7. Edit `config/settings.json`:
   - Replace the sample `user_id`, `guild_id`, and `channel_id`
   - Set `enabled` to `true`
   - Adjust `schedule_time`, `timezone`, and `prompt_set`
8. Edit `config/prompts.json` if you want custom journaling questions.
9. Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

10. Run the bot:

```bash
.venv/bin/python main.py
```

If you prefer the shorter `python3 main.py` form, make sure the virtual environment is activated in the same shell first with `source .venv/bin/activate`.

## Commands

- `!help`
- `!status`
- `!questions`
- `!time HH:MM`
- `!timezone Area/City`
- `!done`
- `!startnow`
- `!stats week`
- `!stats month`
- `!setupuser @user #channel`

`!setupuser` requires `Manage Server` permission and is useful for adding a friend without editing tracked config files.

## How The Journal Flow Works

1. At the configured time, the bot mentions the user in their configured private channel.
2. The bot sends each journal question as its own message.
3. The user replies directly to whichever question messages they want to answer.
4. The user sends `!done` when finished.
5. The bot posts a compiled journal entry ordered by the original question list, not by reply order.
6. Unanswered questions are omitted from the final output.

For testing, you can run `!startnow` in your configured journal channel to start today’s session immediately instead of waiting for the scheduled time.

## Data And Sharing

- Secrets stay in `.env`.
- Example config stays committed to GitHub.
- Personal runtime changes from bot commands are written to `data/runtime/`.
- Completed journals are written to `data/journals/`.
- Runtime data is ignored by Git so friends can self-host with their own state.

## Notes

- v1 is designed for private server channels, not DMs.
- The host machine needs to stay online for scheduled prompts to fire.
- Stats are numeric only in v1. Graphing can be added later without changing the storage model much.




All of this was written by ChatGPT Codex. None of this was written by me except this line.