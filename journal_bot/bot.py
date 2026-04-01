from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import commands

from .config import BotSettings, ConfigError, build_paths, ensure_data_dirs, load_bot_settings, save_runtime_user_override
from .formatter import format_compiled_entry, format_prompt_preview
from .models import ActiveSession, CompletedEntry, UserConfig
from .scheduler import DailyScheduler, parse_schedule_time, user_local_now
from .storage import LocalStorage

LOGGER = logging.getLogger("journal_bot")


class JournalBot(commands.Bot):
    def __init__(self, settings: BotSettings, storage: LocalStorage, app_root: Path) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        super().__init__(command_prefix=settings.command_prefix, intents=intents, help_command=None)
        self.settings = settings
        self.storage = storage
        self.app_root = app_root
        self.scheduler = DailyScheduler(self.maybe_start_due_sessions)
        self.active_sessions: dict[str, ActiveSession] = {
            session.session_id: session for session in storage.load_active_sessions()
        }
        self._register_commands()

    async def setup_hook(self) -> None:
        self.scheduler.start()

    async def on_ready(self) -> None:
        LOGGER.info("Logged in as %s across %s guild(s)", self.user, len(self.guilds))
        await self._validate_configured_targets()

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            if ctx.command and ctx.command.name == "time":
                await ctx.send("Use `!time HH:MM`, for example `!time 21:30`.")
                return
            if ctx.command and ctx.command.name == "timezone":
                await ctx.send("Use `!timezone Area/City`, for example `!timezone America/Phoenix`.")
                return
            if ctx.command and ctx.command.name == "stats":
                await ctx.send("Use `!stats week` or `!stats month`.")
                return
            if ctx.command and ctx.command.name == "setupuser":
                await ctx.send("Use `!setupuser @user #private-channel`.")
                return
            if ctx.command and ctx.command.name == "startnow":
                await ctx.send("Use `!startnow` in your configured journal channel.")
                return
        if isinstance(error, commands.BadArgument):
            if ctx.command and ctx.command.name == "setupuser":
                await ctx.send("Use `!setupuser @user #private-channel`.")
                return
        raise error

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        await self._capture_reply(message)
        await self.process_commands(message)

    async def maybe_start_due_sessions(self) -> None:
        await self.wait_until_ready()
        for user_config in self._iter_enabled_users():
            now_local = user_local_now(user_config.timezone)
            try:
                scheduled_hour, scheduled_minute = parse_schedule_time(user_config.schedule_time)
            except ValueError:
                LOGGER.warning("Skipping user %s due to invalid schedule time.", user_config.user_id)
                continue
            if self._find_any_active_session_for_user(user_config.user_id):
                continue
            if (now_local.hour, now_local.minute) != (scheduled_hour, scheduled_minute):
                continue
            if self._find_active_session(user_config.user_id, user_config.channel_id, now_local.date().isoformat()):
                continue
            if self.storage.has_completed_entry(user_config.user_id, now_local.date().isoformat()):
                continue
            await self.start_session_for_user(user_config, now_local)

    async def start_session_for_user(self, user_config: UserConfig, now_local: datetime | None = None) -> ActiveSession | None:
        if user_config.channel_id is None:
            LOGGER.warning("User %s has no journal channel configured.", user_config.user_id)
            return None
        channel = self.get_channel(user_config.channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(user_config.channel_id)
            except discord.DiscordException:
                LOGGER.warning("Unable to fetch channel %s for user %s.", user_config.channel_id, user_config.user_id)
                return None
        if not hasattr(channel, "send"):
            LOGGER.warning("Configured channel %s is not messageable.", user_config.channel_id)
            return None
        questions = self.settings.prompts[user_config.prompt_set]
        now_local = now_local or user_local_now(user_config.timezone)
        intro = (
            f"<@{user_config.user_id}> time to journal for `{now_local.date().isoformat()}`.\n"
            f"Reply directly to each question message you want to answer, then use `{self.command_prefix}done` when you're finished."
        )
        await channel.send(intro)
        question_message_ids: list[int] = []
        for index, question in enumerate(questions, start=1):
            sent = await channel.send(f"**Question {index}:** {question}")
            question_message_ids.append(sent.id)
        session = ActiveSession(
            session_id=uuid.uuid4().hex,
            user_id=user_config.user_id,
            guild_id=user_config.guild_id,
            channel_id=user_config.channel_id,
            date_key=now_local.date().isoformat(),
            timezone=user_config.timezone,
            prompt_set=user_config.prompt_set,
            questions=questions,
            question_message_ids=question_message_ids,
            started_at=now_local.isoformat(),
        )
        self.active_sessions[session.session_id] = session
        self.storage.save_active_session(session)
        return session

    async def _capture_reply(self, message: discord.Message) -> None:
        if message.reference is None or message.reference.message_id is None:
            return
        session = self._find_active_session_by_context(message.author.id, message.channel.id)
        if session is None:
            return
        if message.reference.message_id not in session.question_message_ids:
            return
        question_index = session.question_message_ids.index(message.reference.message_id)
        content = message.content.strip()
        if not content:
            await message.channel.send("That reply was empty, so I left the question unanswered.")
            return
        session.set_answer(question_index, content)
        self.storage.save_active_session(session)
        await message.add_reaction("📝")

    def _iter_enabled_users(self) -> list[UserConfig]:
        return [
            user for user in self.settings.users if user.enabled and user.channel_id is not None and user.guild_id is not None
        ]

    def _find_user_config(self, user_id: int) -> UserConfig | None:
        for user in self.settings.users:
            if user.user_id == user_id:
                return user
        return None

    def _find_active_session_by_context(self, user_id: int, channel_id: int) -> ActiveSession | None:
        for session in self.active_sessions.values():
            if session.user_id == user_id and session.channel_id == channel_id:
                return session
        return None

    def _find_any_active_session_for_user(self, user_id: int) -> ActiveSession | None:
        for session in self.active_sessions.values():
            if session.user_id == user_id:
                return session
        return None

    def _find_active_session(self, user_id: int, channel_id: int | None, date_key: str) -> ActiveSession | None:
        for session in self.active_sessions.values():
            if session.user_id == user_id and session.channel_id == channel_id and session.date_key == date_key:
                return session
        return None

    def _upsert_user(self, user_config: UserConfig) -> None:
        for index, existing in enumerate(self.settings.users):
            if existing.user_id == user_config.user_id:
                self.settings.users[index] = user_config
                break
        else:
            self.settings.users.append(user_config)
        save_runtime_user_override(build_paths(self.app_root), user_config)

    def _register_commands(self) -> None:
        async def help_cmd(ctx: commands.Context) -> None:
            await self.help_command_impl(ctx)

        async def done_cmd(ctx: commands.Context) -> None:
            await self.done_command(ctx)

        async def status_cmd(ctx: commands.Context) -> None:
            await self.status_command(ctx)

        async def questions_cmd(ctx: commands.Context) -> None:
            await self.questions_command(ctx)

        async def time_cmd(ctx: commands.Context, time_value: str) -> None:
            await self.time_command(ctx, time_value)

        async def timezone_cmd(ctx: commands.Context, timezone_name: str) -> None:
            await self.timezone_command(ctx, timezone_name)

        async def stats_cmd(ctx: commands.Context, window: str) -> None:
            await self.stats_command(ctx, window)

        async def setupuser_cmd(
            ctx: commands.Context,
            member: discord.Member,
            channel: discord.TextChannel,
        ) -> None:
            await self.setupuser_command(ctx, member, channel)

        async def startnow_cmd(ctx: commands.Context) -> None:
            await self.startnow_command(ctx)

        self.add_command(commands.Command(help_cmd, name="help"))
        self.add_command(commands.Command(done_cmd, name="done"))
        self.add_command(commands.Command(status_cmd, name="status"))
        self.add_command(commands.Command(questions_cmd, name="questions"))
        self.add_command(commands.Command(time_cmd, name="time"))
        self.add_command(commands.Command(timezone_cmd, name="timezone"))
        self.add_command(commands.Command(stats_cmd, name="stats"))
        self.add_command(commands.Command(setupuser_cmd, name="setupuser"))
        self.add_command(commands.Command(startnow_cmd, name="startnow"))

    async def help_command_impl(self, ctx: commands.Context) -> None:
        lines = [
            f"`{self.command_prefix}help` - show this message",
            f"`{self.command_prefix}status` - show your current setup and active session",
            f"`{self.command_prefix}questions` - preview your active prompt set",
            f"`{self.command_prefix}time HH:MM` - change your daily prompt time",
            f"`{self.command_prefix}timezone Area/City` - change your timezone",
            f"`{self.command_prefix}done` - finish today’s session",
            f"`{self.command_prefix}startnow` - trigger today’s journal session immediately",
            f"`{self.command_prefix}stats week` - show the last 7 days",
            f"`{self.command_prefix}stats month` - show the last 30 days",
            f"`{self.command_prefix}setupuser @user #channel` - admin setup for a user",
        ]
        await ctx.send("\n".join(lines))

    async def done_command(self, ctx: commands.Context) -> None:
        session = self._find_active_session_by_context(ctx.author.id, ctx.channel.id)
        if session is None:
            await ctx.send("You don't have an active journal session in this channel.")
            return
        compiled_message = format_compiled_entry(session)
        sent = await ctx.send(compiled_message)
        completed_at = datetime.now(ZoneInfo(session.timezone))
        entry = CompletedEntry.from_session(session, completed_at, sent.id)
        self.storage.save_completed_entry(entry)
        self.storage.delete_active_session(session.session_id)
        self.active_sessions.pop(session.session_id, None)
        await ctx.send("Journal session saved. Nice work showing up today.")

    async def status_command(self, ctx: commands.Context) -> None:
        user_config = self._find_user_config(ctx.author.id)
        session = self._find_active_session_by_context(ctx.author.id, ctx.channel.id)
        if user_config is None:
            await ctx.send("You're not configured yet. Ask an admin to run `!setupuser @you #your-channel`.")
            return
        now_local = user_local_now(user_config.timezone).date()
        completion_exists = self.storage.has_completed_entry(ctx.author.id, now_local.isoformat())
        lines = [
            f"Enabled: `{user_config.enabled}`",
            f"Prompt set: `{user_config.prompt_set}`",
            f"Schedule: `{user_config.schedule_time}`",
            f"Timezone: `{user_config.timezone}`",
            f"Configured channel: `{user_config.channel_id}`",
            f"Local date: `{now_local.isoformat()}`",
            f"Completed today: `{completion_exists}`",
        ]
        if session:
            lines.append(f"Active session date: `{session.date_key}` with `{len(session.answers)}` saved answers.")
        else:
            lines.append("No active session in this channel.")
        await ctx.send("\n".join(lines))

    async def questions_command(self, ctx: commands.Context) -> None:
        user_config = self._find_user_config(ctx.author.id)
        if user_config is None:
            await ctx.send("You're not configured yet.")
            return
        questions = self.settings.prompts[user_config.prompt_set]
        await ctx.send(format_prompt_preview(questions))

    async def time_command(self, ctx: commands.Context, time_value: str) -> None:
        user_config = self._find_user_config(ctx.author.id)
        if user_config is None:
            await ctx.send("You're not configured yet.")
            return
        try:
            parse_schedule_time(time_value)
        except ValueError:
            await ctx.send("Use 24-hour time in `HH:MM` format, for example `!time 21:30`.")
            return
        updated = UserConfig(
            user_id=user_config.user_id,
            guild_id=user_config.guild_id,
            channel_id=user_config.channel_id,
            schedule_time=time_value,
            timezone=user_config.timezone,
            prompt_set=user_config.prompt_set,
            enabled=user_config.enabled,
        )
        self._upsert_user(updated)
        await ctx.send(f"Your daily journal time is now `{time_value}` in `{updated.timezone}`.")

    async def timezone_command(self, ctx: commands.Context, timezone_name: str) -> None:
        user_config = self._find_user_config(ctx.author.id)
        if user_config is None:
            await ctx.send("You're not configured yet.")
            return
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            await ctx.send("That timezone wasn't recognized. Use an IANA value like `America/Phoenix`.")
            return
        updated = UserConfig(
            user_id=user_config.user_id,
            guild_id=user_config.guild_id,
            channel_id=user_config.channel_id,
            schedule_time=user_config.schedule_time,
            timezone=timezone_name,
            prompt_set=user_config.prompt_set,
            enabled=user_config.enabled,
        )
        self._upsert_user(updated)
        await ctx.send(f"Your timezone is now `{timezone_name}`.")

    async def stats_command(self, ctx: commands.Context, window: str) -> None:
        window = window.lower().strip()
        if window not in {"week", "month"}:
            await ctx.send("Use `!stats week` or `!stats month`.")
            return
        user_config = self._find_user_config(ctx.author.id)
        if user_config is None:
            await ctx.send("You're not configured yet.")
            return
        now_local = user_local_now(user_config.timezone).date()
        days = 7 if window == "week" else 30
        start_date = now_local - timedelta(days=days - 1)
        stats = self.storage.completion_stats(ctx.author.id, start_date, now_local)
        await ctx.send(
            "\n".join(
                [
                    f"`{window}` stats for <@{ctx.author.id}>",
                    f"Completed days: `{stats['completed_days']}` / `{stats['total_days']}`",
                    f"Completion rate: `{stats['percentage']:.1f}%`",
                    f"Completed dates: `{', '.join(stats['completed_dates']) if stats['completed_dates'] else 'none yet'}`",
                ]
            )
        )

    async def setupuser_command(
        self,
        ctx: commands.Context,
        member: discord.Member,
        channel: discord.TextChannel,
    ) -> None:
        if not ctx.guild or not ctx.author.guild_permissions.manage_guild:
            await ctx.send("You need the `Manage Server` permission to use `!setupuser`.")
            return
        if not self.settings.allow_runtime_user_setup:
            await ctx.send("Runtime user setup is disabled in config/settings.json.")
            return
        existing = self._find_user_config(member.id)
        prompt_set = existing.prompt_set if existing else next(iter(self.settings.prompts.keys()))
        schedule_time = existing.schedule_time if existing else "21:00"
        timezone_name = existing.timezone if existing else self.settings.default_timezone
        updated = UserConfig(
            user_id=member.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            channel_id=channel.id,
            schedule_time=schedule_time,
            timezone=timezone_name,
            prompt_set=prompt_set,
            enabled=True,
        )
        self._upsert_user(updated)
        await ctx.send(
            f"Configured <@{member.id}> to journal in {channel.mention} at `{schedule_time}` using `{timezone_name}`."
        )

    async def startnow_command(self, ctx: commands.Context) -> None:
        user_config = self._find_user_config(ctx.author.id)
        if user_config is None:
            await ctx.send("You're not configured yet.")
            return
        if user_config.channel_id != ctx.channel.id:
            await ctx.send("Run `!startnow` from your configured journal channel.")
            return
        existing_session = self._find_any_active_session_for_user(ctx.author.id)
        if existing_session is not None:
            await ctx.send("You already have an active journal session.")
            return
        now_local = user_local_now(user_config.timezone)
        if self.storage.has_completed_entry(ctx.author.id, now_local.date().isoformat()):
            await ctx.send("Today's journal is already complete.")
            return
        session = await self.start_session_for_user(user_config, now_local)
        if session is None:
            await ctx.send("I couldn't start your journal session. Check the bot logs for channel/setup issues.")
            return
        await ctx.send("Started today's journal session.")

    async def _validate_configured_targets(self) -> None:
        for user_config in self._iter_enabled_users():
            guild = self.get_guild(user_config.guild_id) if user_config.guild_id is not None else None
            if guild is None:
                LOGGER.warning(
                    "Configured guild %s for user %s is not visible to the bot.",
                    user_config.guild_id,
                    user_config.user_id,
                )
            channel = self.get_channel(user_config.channel_id) if user_config.channel_id is not None else None
            if channel is None and user_config.channel_id is not None:
                try:
                    channel = await self.fetch_channel(user_config.channel_id)
                except discord.DiscordException:
                    LOGGER.warning(
                        "Configured channel %s for user %s could not be fetched.",
                        user_config.channel_id,
                        user_config.user_id,
                    )
                    continue
            if channel is not None:
                LOGGER.info(
                    "Validated journal target for user %s: guild=%s channel=%s",
                    user_config.user_id,
                    user_config.guild_id,
                    user_config.channel_id,
                )


def run_bot() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    paths = build_paths()
    ensure_data_dirs(paths)
    try:
        settings = load_bot_settings(paths)
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    storage = LocalStorage(paths)
    bot = JournalBot(settings=settings, storage=storage, app_root=paths.root)
    bot.run(settings.token, log_handler=None)
