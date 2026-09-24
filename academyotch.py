import os
import json
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import ui, Interaction, app_commands
from discord.ext import commands, tasks


# ============================================================
# НАСТРОЙКИ
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "Не найдена переменная окружения DISCORD_TOKEN."
    )

# ID сервера
GUILD_ID = 1534179608390406308

# Канал подачи отчётов и статистики
REPORTS_CHANNEL_ID = 1552806315472982086
STATS_CHANNEL_ID = 1552806315472982086

# Discord ID проверяющего администратора
REVIEWER_ID = 1416863224430596107

# Роль участника мафии
MAFIA_ROLE_NAME = "academy"

# Роли, которые снимаются после 5 выговоров
ROLES_TO_REMOVE_AFTER_FIVE = [
    "academy"
]

# Минимум баллов за неделю
REQUIRED_WEEKLY_POINTS = 5

# Максимум выговоров
MAX_REPRIMANDS = 5

# Файл хранения данных
DATA_FILE = "mafia_reports_data.json"

# Часовой пояс Москвы
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

# Разрешённые расширения скриншотов
ALLOWED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif"
}


# ============================================================
# INTENTS
# ============================================================

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.message_content = True


# ============================================================
# ГЛОБАЛЬНЫЕ ДАННЫЕ
# ============================================================

# Структура:
#
# {
#     "users": {
#         "USER_ID": {
#             "total_points": 0,
#             "reprimands": 0
#         }
#     },
#     "weekly_points": {
#         "WEEK_KEY": {
#             "USER_ID": 5
#         }
#     },
#     "reports": {
#         "REPORT_ID": {
#             "report_id": "...",
#             "user_id": 123,
#             "guild_id": 123,
#             "week_key": "...",
#             "requested_points": 5,
#             "accepted_points": 0,
#             "comment": "...",
#             "attachment_urls": [],
#             "status": "pending",
#             "reviewer_id": 123,
#             "reason": "",
#             "created_at": "..."
#         }
#     },
#     "panel_message_id": 0,
#     "stats_message_id": 0
# }
#

data = {
    "users": {},
    "weekly_points": {},
    "reports": {},
    "panel_message_id": None,
    "stats_message_id": None
}

data_loaded = False


# ============================================================
# БЕЗОПАСНЫЕ ДАННЫЕ
# ============================================================

def save_data():
    """Сохраняет все данные в JSON-файл."""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=4
            )

        print("💾 Данные сохранены")

    except OSError as error:
        print(
            f"❌ Ошибка сохранения данных: {error}"
        )


def load_data():
    """Загружает данные из JSON-файла."""
    global data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            loaded_data = json.load(file)

        if not isinstance(loaded_data, dict):
            raise ValueError(
                "Корневой объект JSON должен быть словарём."
            )

        data = {
            "users": loaded_data.get(
                "users",
                {}
            ),
            "weekly_points": loaded_data.get(
                "weekly_points",
                {}
            ),
            "reports": loaded_data.get(
                "reports",
                {}
            ),
            "panel_message_id": loaded_data.get(
                "panel_message_id"
            ),
            "stats_message_id": loaded_data.get(
                "stats_message_id"
            )
        }

        print(
            f"💾 Загружено пользователей: "
            f"{len(data['users'])}"
        )

        print(
            f"💾 Загружено отчётов: "
            f"{len(data['reports'])}"
        )

    except FileNotFoundError:
        print(
            "💾 Файл данных не найден. "
            "Будет создан новый."
        )

    except (json.JSONDecodeError, ValueError) as error:
        print(
            f"❌ Ошибка структуры файла данных: "
            f"{error}"
        )

    except OSError as error:
        print(
            f"❌ Ошибка загрузки данных: {error}"
        )


def ensure_user_data(user_id: int):
    """Создаёт запись пользователя, если её нет."""
    user_id = str(user_id)

    if user_id not in data["users"]:
        data["users"][user_id] = {
            "total_points": 0,
            "reprimands": 0
        }

    return data["users"][user_id]


# ============================================================
# ВРЕМЯ И НЕДЕЛИ
# ============================================================

def now_moscow() -> datetime:
    """Возвращает текущее время Москвы."""
    return datetime.now(MOSCOW_TZ)


def get_week_key(moment: datetime | None = None) -> str:
    """
    Возвращает ключ текущей отчётной недели.

    Неделя начинается в понедельник
    и заканчивается в воскресенье 23:59.
    """
    if moment is None:
        moment = now_moscow()

    moment = moment.astimezone(MOSCOW_TZ)

    monday = moment - timedelta(
        days=moment.weekday()
    )

    monday = monday.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    sunday = monday + timedelta(days=6)

    return (
        f"{monday.strftime('%Y-%m-%d')}_"
        f"{sunday.strftime('%Y-%m-%d')}"
    )


def get_week_dates(
    week_key: str | None = None
):
    """Возвращает дату начала и окончания недели."""
    if week_key is None:
        week_key = get_week_key()

    try:
        monday_text, sunday_text = week_key.split(
            "_"
        )

        monday = datetime.strptime(
            monday_text,
            "%Y-%m-%d"
        ).replace(
            tzinfo=MOSCOW_TZ
        )

        sunday = datetime.strptime(
            sunday_text,
            "%Y-%m-%d"
        ).replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
            tzinfo=MOSCOW_TZ
        )

        return monday, sunday

    except (ValueError, AttributeError):
        current_monday = (
            now_moscow()
            - timedelta(
                days=now_moscow().weekday()
            )
        ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        current_sunday = current_monday + timedelta(
            days=6,
            hours=23,
            minutes=59,
            seconds=59
        )

        return current_monday, current_sunday


def get_week_display(
    week_key: str | None = None
) -> str:
    """Красивое отображение недели."""
    monday, sunday = get_week_dates(
        week_key
    )

    return (
        f"{monday.strftime('%d.%m.%Y')} — "
        f"{sunday.strftime('%d.%m.%Y')}"
    )


def get_weekly_points(
    user_id: int,
    week_key: str | None = None
) -> int:
    """Возвращает баллы пользователя за неделю."""
    if week_key is None:
        week_key = get_week_key()

    week_data = data["weekly_points"].get(
        week_key,
        {}
    )

    return int(
        week_data.get(
            str(user_id),
            0
        )
    )


def add_weekly_points(
    user_id: int,
    points: int,
    week_key: str | None = None
):
    """Добавляет баллы пользователю за неделю."""
    if week_key is None:
        week_key = get_week_key()

    if week_key not in data["weekly_points"]:
        data["weekly_points"][week_key] = {}

    user_key = str(user_id)

    current_points = int(
        data["weekly_points"][week_key].get(
            user_key,
            0
        )
    )

    data["weekly_points"][week_key][user_key] = (
        current_points + points
    )

    user_data = ensure_user_data(
        user_id
    )

    user_data["total_points"] = int(
        user_data.get(
            "total_points",
            0
        )
    ) + points


# ============================================================
# РОЛИ
# ============================================================

def has_mafia_role(member: discord.Member) -> bool:
    """Проверяет наличие роли academy."""
    target_name = MAFIA_ROLE_NAME.lower()

    return any(
        role.name.lower() == target_name
        for role in member.roles
    )


def find_role_by_name(
    guild: discord.Guild,
    role_name: str
):
    """Находит роль по названию."""
    target_name = role_name.lower()

    for role in guild.roles:
        if role.name.lower() == target_name:
            return role

    return None


async def remove_mafia_roles(
    member: discord.Member,
    reason: str
):
    """Снимает роли, указанные после 5 выговоров."""
    roles_to_remove = []

    for role_name in ROLES_TO_REMOVE_AFTER_FIVE:
        role = find_role_by_name(
            member.guild,
            role_name
        )

        if role and role in member.roles:
            roles_to_remove.append(role)

    if not roles_to_remove:
        print(
            f"⚠️ У {member} не найдено ролей "
            "для снятия."
        )
        return

    try:
        await member.remove_roles(
            *roles_to_remove,
            reason=reason
        )

        print(
            f"✅ Сняты роли у {member}: "
            f"{[role.name for role in roles_to_remove]}"
        )

    except discord.Forbidden:
        print(
            f"❌ Бот не может снять роли у {member}. "
            f"Проверь Manage Roles и иерархию."
        )

    except discord.HTTPException as error:
        print(
            f"❌ Ошибка снятия ролей у {member}: "
            f"{error}"
        )


# ============================================================
# ВЛОЖЕНИЯ И ОТЧЁТЫ
# ============================================================

def is_allowed_image(
    attachment: discord.Attachment
) -> bool:
    """Проверяет расширение изображения."""
    filename = attachment.filename.lower()

    return any(
        filename.endswith(extension)
        for extension in ALLOWED_IMAGE_EXTENSIONS
    )


def get_report_id() -> str:
    """Создаёт уникальный ID отчёта."""
    return str(
        int(
            datetime.now(timezone.utc).timestamp()
            * 1000000
        )
    )


def get_pending_report_for_user(
    user_id: int,
    week_key: str | None = None
):
    """Ищет ожидающий отчёт пользователя."""
    if week_key is None:
        week_key = get_week_key()

    for report in data["reports"].values():
        if (
            int(report.get("user_id", 0)) == user_id
            and report.get("week_key") == week_key
            and report.get("status") == "pending"
        ):
            return report

    return None


def has_accepted_report_for_week(
    user_id: int,
    week_key: str | None = None
) -> bool:
    """Проверяет, был ли уже принятый отчёт."""
    if week_key is None:
        week_key = get_week_key()

    for report in data["reports"].values():
        if (
            int(report.get("user_id", 0)) == user_id
            and report.get("week_key") == week_key
            and report.get("status") == "accepted"
        ):
            return True

    return False


# ============================================================
# EMBED ОТЧЁТА
# ============================================================

def create_report_embed(
    report: dict,
    member: discord.Member | None = None
) -> discord.Embed:
    """Создаёт Embed для отчёта."""
    status = report.get(
        "status",
        "pending"
    )

    status_text = {
        "pending": "⏳ На проверке",
        "accepted": "✅ Принят",
        "rejected": "❌ Отклонён"
    }.get(
        status,
        status
    )

    if member:
        user_text = (
            f"{member.mention}\n"
            f"`{member}`\n"
            f"ID: `{member.id}`"
        )
    else:
        user_text = (
            f"<@{report['user_id']}>\n"
            f"ID: `{report['user_id']}`"
        )

    embed = discord.Embed(
        title="📨 Недельный отчёт",
        description=(
            "Проверьте скриншоты и решите, "
            "засчитать ли баллы."
        ),
        color=discord.Color.orange()
        if status == "pending"
        else (
            discord.Color.green()
            if status == "accepted"
            else discord.Color.red()
        )
    )

    embed.add_field(
        name="👤 Участник",
        value=user_text,
        inline=False
    )

    embed.add_field(
        name="📅 Отчётная неделя",
        value=get_week_display(
            report.get("week_key")
        ),
        inline=True
    )

    embed.add_field(
        name="🎯 Заявлено баллов",
        value=str(
            report.get(
                "requested_points",
                0
            )
        ),
        inline=True
    )

    embed.add_field(
        name="📊 Баллы за неделю",
        value=(
            f"{get_weekly_points("
                f"int(report['user_id']), "
                f"report.get('week_key')"
            )}/{REQUIRED_WEEKLY_POINTS}"
        ),
        inline=True
    )

    user_data = ensure_user_data(
        int(report["user_id"])
    )

    embed.add_field(
        name="⚠️ Выговоры",
        value=(
            f"{user_data.get('reprimands', 0)}"
            f"/{MAX_REPRIMANDS}"
        ),
        inline=True
    )

    embed.add_field(
        name="📌 Статус",
        value=status_text,
        inline=True
    )

    comment = report.get(
        "comment",
        ""
    ).strip()

    embed.add_field(
        name="💬 Комментарий участника",
        value=comment[:1024]
        if comment
        else "Не указан",
        inline=False
    )

    reason = report.get(
        "reason",
        ""
    ).strip()

    if reason:
        embed.add_field(
            name="📝 Причина отказа",
            value=reason[:1024],
            inline=False
        )

    embed.set_footer(
        text=(
            f"ID отчёта: {report.get('report_id')}"
        )
    )

    return embed


# ============================================================
# EMBED СТАТИСТИКИ
# ============================================================

def create_statistics_embed(
    guild: discord.Guild
) -> discord.Embed:
    """Создаёт Embed с общей статистикой."""
    week_key = get_week_key()

    embed = discord.Embed(
        title="📊 Статистика еженедельных отчётов",
        description=(
            f"Текущая неделя: "
            f"**{get_week_display(week_key)}**\n"
            f"Необходимый минимум: "
            f"**{REQUIRED_WEEKLY_POINTS} баллов**"
        ),
        color=discord.Color.blurple(),
        timestamp=now_moscow()
    )

    members = []

    for member in guild.members:
        if member.bot:
            continue

        if has_mafia_role(member):
            members.append(member)

    if not members:
        embed.add_field(
            name="👥 Участники",
            value=(
                "Участники с ролью "
                f"`{MAFIA_ROLE_NAME}` не найдены."
            ),
            inline=False
        )

        return embed

    members.sort(
        key=lambda member: get_weekly_points(
            member.id,
            week_key
        ),
        reverse=True
    )

    lines = []

    for index, member in enumerate(
        members,
        start=1
    ):
        user_data = ensure_user_data(
            member.id
        )

        weekly_points = get_weekly_points(
            member.id,
            week_key
        )

        total_points = int(
            user_data.get(
                "total_points",
                0
            )
        )

        reprimands = int(
            user_data.get(
                "reprimands",
                0
            )
        )

        if weekly_points >= REQUIRED_WEEKLY_POINTS:
            status = "✅"
        else:
            status = "⏳"

        if reprimands >= MAX_REPRIMANDS:
            status = "🚫"

        lines.append(
            f"**{index}.** {member.mention}\n"
            f"└ {status} Неделя: "
            f"**{weekly_points}/{REQUIRED_WEEKLY_POINTS}** "
            f"· Всего: **{total_points}** "
            f"· В/г: **{reprimands}/{MAX_REPRIMANDS}**"
        )

    # Discord ограничивает размер поля
    chunks = []
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 2 > 1000:
            chunks.append(current_chunk)
            current_chunk = ""

        current_chunk += line + "\n\n"

    if current_chunk:
        chunks.append(current_chunk)

    for index, chunk in enumerate(chunks):
        field_name = (
            "👥 Участники"
            if index == 0
            else f"👥 Участники — часть {index + 1}"
        )

        embed.add_field(
            name=field_name,
            value=chunk,
            inline=False
        )

    embed.set_footer(
        text=(
            "Баллы и выговоры обновляются автоматически"
        )
    )

    return embed


# ============================================================
# КОМПОНЕНТЫ ЗАЯВКИ
# ============================================================

class ReportModal(ui.Modal):
    """Форма отправки отчёта."""

    def __init__(
        self,
        member: discord.Member
    ):
        super().__init__(
            title="Подача недельного отчёта"
        )

        self.member = member

        self.points_input = ui.TextInput(
            label="Количество заявленных баллов",
            placeholder="Например: 5",
            min_length=1,
            max_length=3,
            required=True
        )

        self.comment_input = ui.TextInput(
            label="Комментарий к отчёту",
            placeholder=(
                "Кратко опишите, за что получены баллы"
            ),
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=False
        )

        self.add_item(
            self.points_input
        )

        self.add_item(
            self.comment_input
        )

    async def on_submit(
        self,
        interaction: Interaction
    ):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "❌ Отчёты принимаются только на сервере.",
                ephemeral=True
            )
            return

        if not has_mafia_role(self.member):
            await interaction.response.send_message(
                f"❌ У вас нет роли `{MAFIA_ROLE_NAME}`.",
                ephemeral=True
            )
            return

        try:
            requested_points = int(
                str(self.points_input.value).strip()
            )

        except ValueError:
            await interaction.response.send_message(
                "❌ Количество баллов должно быть числом.",
                ephemeral=True
            )
            return

        if requested_points <= 0:
            await interaction.response.send_message(
                "❌ Количество баллов должно быть больше нуля.",
                ephemeral=True
            )
            return

        if requested_points > 100:
            await interaction.response.send_message(
                "❌ Нельзя указать больше 100 баллов.",
                ephemeral=True
            )
            return

        week_key = get_week_key()

        if get_pending_report_for_user(
            self.member.id,
            week_key
        ):
            await interaction.response.send_message(
                "❌ У вас уже есть отчёт на проверке.",
                ephemeral=True
            )
            return

        if has_accepted_report_for_week(
            self.member.id,
            week_key
        ):
            await interaction.response.send_message(
                "❌ За эту неделю у вас уже есть "
                "принятый отчёт.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            (
                "📎 Теперь отправьте в этот канал "
                "сообщение со скриншотами отчёта.\n\n"
                "В одном сообщении можно прикрепить "
                "несколько изображений.\n"
                "Это сообщение должно быть отправлено "
                "в течение 10 минут."
            ),
            ephemeral=True
        )

        try:
            attachment_message = await bot.wait_for(
                "message",
                timeout=600,
                check=lambda message: (
                    message.author.id == self.member.id
                    and message.channel.id
                    == REPORTS_CHANNEL_ID
                    and len(message.attachments) > 0
                )
            )

        except asyncio.TimeoutError:
            try:
                await self.member.send(
                    "⌛ Время ожидания скриншотов истекло. "
                    "Отчёт не был создан."
                )
            except discord.Forbidden:
                pass

            return

        image_attachments = [
            attachment
            for attachment in attachment_message.attachments
            if is_allowed_image(attachment)
        ]

        if not image_attachments:
            await self.member.send(
                "❌ Отчёт не принят: "
                "сообщение не содержит изображений."
            )

            return

        report_id = get_report_id()

        report = {
            "report_id": report_id,
            "user_id": self.member.id,
            "guild_id": guild.id,
            "week_key": week_key,
            "requested_points": requested_points,
            "accepted_points": 0,
            "comment": str(
                self.comment_input.value
            ).strip(),
            "attachment_urls": [
                attachment.url
                for attachment in image_attachments
            ],
            "source_message_id": attachment_message.id,
            "status": "pending",
            "reviewer_id": None,
            "reason": "",
            "created_at": now_moscow().isoformat()
        }

        data["reports"][report_id] = report

        save_data()

        reviewer = bot.get_user(REVIEWER_ID)

        if reviewer is None:
            try:
                reviewer = await bot.fetch_user(
                    REVIEWER_ID
                )
            except discord.HTTPException:
                reviewer = None

        if reviewer is None:
            await interaction.followup.send(
                "⚠️ Отчёт сохранён, но проверяющий "
                "администратор не найден.",
                ephemeral=True
            )
            return

        review_embed = create_report_embed(
            report,
            self.member
        )

        try:
            review_message = await reviewer.send(
                embed=review_embed,
                view=ReportReviewView(
                    report_id
                )
            )

            report["review_message_id"] = (
                review_message.id
            )

            save_data()

            for attachment in image_attachments:
                try:
                    await reviewer.send(
                        attachment.url
                    )
                except discord.HTTPException:
                    pass

            await self.member.send(
                (
                    "✅ Ваш отчёт отправлен "
                    "на проверку.\n"
                    f"Заявлено баллов: **{requested_points}**\n"
                    f"Неделя: **{get_week_display(week_key)}**"
                )
            )

            await update_statistics_message()

        except discord.Forbidden:
            await interaction.followup.send(
                (
                    "❌ Не удалось отправить отчёт "
                    "проверяющему в личные сообщения.\n"
                    "Проверьте, что личные сообщения открыты."
                ),
                ephemeral=True
            )

        except discord.HTTPException as error:
            print(
                f"❌ Ошибка отправки отчёта: {error}"
            )


class SubmitReportView(ui.View):
    """Постоянная кнопка подачи отчёта."""

    def __init__(self):
        super().__init__(
            timeout=None
        )

    @ui.button(
        label="Подать отчёт",
        emoji="📨",
        style=discord.ButtonStyle.primary,
        custom_id="mafia_submit_report"
    )
    async def submit_report(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Не удалось определить участника.",
                ephemeral=True
            )
            return

        if not has_mafia_role(member):
            await interaction.response.send_message(
                f"❌ Для подачи отчёта нужна роль "
                f"`{MAFIA_ROLE_NAME}`.",
                ephemeral=True
            )
            return

        week_key = get_week_key()

        if get_pending_report_for_user(
            member.id,
            week_key
        ):
            await interaction.response.send_message(
                "❌ У вас уже есть отчёт на проверке.",
                ephemeral=True
            )
            return

        if has_accepted_report_for_week(
            member.id,
            week_key
        ):
            await interaction.response.send_message(
                "❌ За эту неделю отчёт уже принят.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            ReportModal(member)
        )

    @ui.button(
        label="Моя статистика",
        emoji="📊",
        style=discord.ButtonStyle.secondary,
        custom_id="mafia_my_statistics"
    )
    async def my_statistics(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        member = interaction.user

        user_data = ensure_user_data(
            member.id
        )

        weekly_points = get_weekly_points(
            member.id
        )

        total_points = int(
            user_data.get(
                "total_points",
                0
            )
        )

        reprimands = int(
            user_data.get(
                "reprimands",
                0
            )
        )

        embed = discord.Embed(
            title="📊 Ваша статистика",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="📅 Текущая неделя",
            value=(
                f"{weekly_points}/"
                f"{REQUIRED_WEEKLY_POINTS} баллов"
            ),
            inline=False
        )

        embed.add_field(
            name="🏆 Всего баллов",
            value=str(total_points),
            inline=True
        )

        embed.add_field(
            name="⚠️ Выговоры",
            value=(
                f"{reprimands}/"
                f"{MAX_REPRIMANDS}"
            ),
            inline=True
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# ============================================================
# ПРОВЕРКА ОТЧЁТА АДМИНИСТРАТОРОМ
# ============================================================

class ReportReviewView(ui.View):
    """Кнопки принятия или отказа в баллах."""

    def __init__(
        self,
        report_id: str
    ):
        super().__init__(
            timeout=None
        )

        self.report_id = report_id

    @ui.button(
        label="Дать баллы",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="mafia_accept_report"
    )
    async def accept_report(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        if interaction.user.id != REVIEWER_ID:
            await interaction.response.send_message(
                "❌ Только проверяющий может "
                "обработать этот отчёт.",
                ephemeral=True
            )
            return

        report = data["reports"].get(
            self.report_id
        )

        if report is None:
            await interaction.response.send_message(
                "❌ Отчёт не найден.",
                ephemeral=True
            )
            return

        if report.get("status") != "pending":
            await interaction.response.send_message(
                "❌ Этот отчёт уже обработан.",
                ephemeral=True
            )
            return

        points = int(
            report.get(
                "requested_points",
                0
            )
        )

        report["status"] = "accepted"
        report["accepted_points"] = points
        report["reviewer_id"] = interaction.user.id
        report["reviewed_at"] = (
            now_moscow().isoformat()
        )

        add_weekly_points(
            int(report["user_id"]),
            points,
            report["week_key"]
        )

        save_data()

        member = None
        guild = bot.get_guild(
            int(report["guild_id"])
        )

        if guild:
            member = guild.get_member(
                int(report["user_id"])
            )

        result_embed = create_report_embed(
            report,
            member
        )

        result_embed.add_field(
            name="✅ Результат",
            value=(
                f"Начислено баллов: **{points}**"
            ),
            inline=False
        )

        await interaction.response.edit_message(
            embed=result_embed,
            view=None
        )

        try:
            user = bot.get_user(
                int(report["user_id"])
            )

            if user is None:
                user = await bot.fetch_user(
                    int(report["user_id"])
                )

            await user.send(
                (
                    "✅ Ваш отчёт принят.\n\n"
                    f"Вам начислено баллов: **{points}**\n"
                    f"За текущую неделю: "
                    f"**{get_weekly_points("
                        f"int(report['user_id']), "
                        f"report['week_key']"
                    )}/{REQUIRED_WEEKLY_POINTS}**"
                )
            )

        except discord.Forbidden:
            print(
                "⚠️ Не удалось отправить результат "
                "игроку в ЛС."
            )

        except discord.HTTPException as error:
            print(
                f"⚠️ Ошибка отправки результата: "
                f"{error}"
            )

        await update_statistics_message()

    @ui.button(
        label="Отказать в баллах",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="mafia_reject_report"
    )
    async def reject_report(
        self,
        interaction: Interaction,
        button: ui.Button
    ):
        if interaction.user.id != REVIEWER_ID:
            await interaction.response.send_message(
                "❌ Только проверяющий может "
                "обработать этот отчёт.",
                ephemeral=True
            )
            return

        report = data["reports"].get(
            self.report_id
        )

        if report is None:
            await interaction.response.send_message(
                "❌ Отчёт не найден.",
                ephemeral=True
            )
            return

        if report.get("status") != "pending":
            await interaction.response.send_message(
                "❌ Этот отчёт уже обработан.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            RejectReportModal(
                self.report_id
            )
        )


class RejectReportModal(ui.Modal):
    """Окно для ввода причины отказа."""

    def __init__(
        self,
        report_id: str
    ):
        super().__init__(
            title="Причина отказа"
        )

        self.report_id = report_id

        self.reason_input = ui.TextInput(
            label="Причина отказа",
            placeholder=(
                "Например: на скриншоте "
                "не видно дату или результат"
            ),
            style=discord.TextStyle.paragraph,
            min_length=3,
            max_length=1000,
            required=True
        )

        self.add_item(
            self.reason_input
        )

    async def on_submit(
        self,
        interaction: Interaction
    ):
        if interaction.user.id != REVIEWER_ID:
            await interaction.response.send_message(
                "❌ У вас нет доступа к проверке.",
                ephemeral=True
            )
            return

        report = data["reports"].get(
            self.report_id
        )

        if report is None:
            await interaction.response.send_message(
                "❌ Отчёт не найден.",
                ephemeral=True
            )
            return

        if report.get("status") != "pending":
            await interaction.response.send_message(
                "❌ Этот отчёт уже обработан.",
                ephemeral=True
            )
            return

        reason = str(
            self.reason_input.value
        ).strip()

        report["status"] = "rejected"
        report["reason"] = reason
        report["reviewer_id"] = interaction.user.id
        report["reviewed_at"] = (
            now_moscow().isoformat()
        )

        save_data()

        member = None
        guild = bot.get_guild(
            int(report["guild_id"])
        )

        if guild:
            member = guild.get_member(
                int(report["user_id"])
            )

        result_embed = create_report_embed(
            report,
            member
        )

        await interaction.response.edit_message(
            embed=result_embed,
            view=None
        )

        try:
            user = bot.get_user(
                int(report["user_id"])
            )

            if user is None:
                user = await bot.fetch_user(
                    int(report["user_id"])
                )

            await user.send(
                (
                    "❌ Ваш отчёт отклонён.\n\n"
                    f"Причина отказа:\n{reason}"
                )
            )

        except discord.Forbidden:
            print(
                "⚠️ Не удалось отправить причину "
                "отказа игроку в ЛС."
            )

        except discord.HTTPException as error:
            print(
                f"⚠️ Ошибка отправки отказа: "
                f"{error}"
            )

        await update_statistics_message()


# ============================================================
# EMBED ПАНЕЛИ
# ============================================================

def create_panel_embed() -> discord.Embed:
    """Создаёт панель подачи отчёта."""
    embed = discord.Embed(
        title="📨 Еженедельные отчёты мафии",
        description=(
            "Каждую неделю участники мафии должны "
            "набрать минимум **5 баллов**.\n\n"
            "**Как подать отчёт:**\n"
            "1. Нажмите кнопку `📨 Подать отчёт`.\n"
            "2. Укажите количество заявленных баллов.\n"
            "3. Напишите комментарий.\n"
            "4. Отправьте сообщение со скриншотами "
            "в этот канал.\n"
            "5. Дождитесь проверки администратора.\n\n"
            "Если за неделю набрано меньше 5 баллов, "
            "участник получает один выговор.\n"
            "После получения 5 выговоров роль "
            "`academy` снимается."
        ),
        color=discord.Color.from_rgb(
            55,
            110,
            190
        )
    )

    embed.add_field(
        name="🎯 Минимум",
        value="5 баллов за неделю",
        inline=True
    )

    embed.add_field(
        name="📅 Конец недели",
        value="Воскресенье, 23:59 МСК",
        inline=True
    )

    embed.add_field(
        name="⚠️ Лимит",
        value="5 выговоров",
        inline=True
    )

    embed.set_footer(
        text=(
            "Отчёты проверяются администратором "
            "вручную"
        )
    )

    return embed


# ============================================================
# ПОДДЕРЖАНИЕ ПАНЕЛИ
# ============================================================

async def ensure_panel_exists():
    """Проверяет и восстанавливает панель."""
    channel = bot.get_channel(
        REPORTS_CHANNEL_ID
    )

    if channel is None:
        print(
            "❌ Канал отчётов не найден."
        )
        return

    if not isinstance(channel, discord.TextChannel):
        print(
            "❌ Канал отчётов должен быть текстовым."
        )
        return

    embed = create_panel_embed()

    if data.get("panel_message_id"):
        try:
            message = await channel.fetch_message(
                int(data["panel_message_id"])
            )

            await message.edit(
                embed=embed,
                view=SubmitReportView()
            )

            return

        except discord.NotFound:
            print(
                "⚠️ Панель отчётов удалена."
            )

        except discord.Forbidden:
            print(
                "❌ Нет доступа к панели отчётов."
            )
            return

        except discord.HTTPException as error:
            print(
                f"❌ Ошибка проверки панели: {error}"
            )

    try:
        async for message in channel.history(
            limit=100
        ):
            if message.author != bot.user:
                continue

            if not message.embeds:
                continue

            title = message.embeds[0].title

            if title == "📨 Еженедельные отчёты мафии":
                data["panel_message_id"] = message.id

                await message.edit(
                    embed=embed,
                    view=SubmitReportView()
                )

                save_data()

                print(
                    "✅ Найдена старая панель отчётов."
                )

                return

    except discord.Forbidden:
        print(
            "❌ Нет права читать историю канала."
        )
        return

    except discord.HTTPException as error:
        print(
            f"❌ Ошибка поиска панели: {error}"
        )
        return

    try:
        message = await channel.send(
            embed=embed,
            view=SubmitReportView()
        )

        data["panel_message_id"] = message.id

        save_data()

        print(
            f"✅ Создана новая панель отчётов: "
            f"{message.id}"
        )

    except discord.Forbidden:
        print(
            "❌ Бот не может создать панель."
        )

    except discord.HTTPException as error:
        print(
            f"❌ Ошибка создания панели: {error}"
        )


# ============================================================
# ПОДДЕРЖАНИЕ СООБЩЕНИЯ СТАТИСТИКИ
# ============================================================

async def update_statistics_message():
    """Обновляет статистику в канале."""
    guild = bot.get_guild(
        GUILD_ID
    )

    if guild is None:
        print(
            "❌ Сервер статистики не найден."
        )
        return

    channel = bot.get_channel(
        STATS_CHANNEL_ID
    )

    if channel is None:
        print(
            "❌ Канал статистики не найден."
        )
        return

    if not isinstance(channel, discord.TextChannel):
        return

    embed = create_statistics_embed(
        guild
    )

    try:
        if data.get("stats_message_id"):
            try:
                message = await channel.fetch_message(
                    int(data["stats_message_id"])
                )

                await message.edit(
                    embed=embed
                )

                return

            except discord.NotFound:
                print(
                    "⚠️ Сообщение статистики удалено."
                )

        async for message in channel.history(
            limit=100
        ):
            if message.author != bot.user:
                continue

            if not message.embeds:
                continue

            title = message.embeds[0].title

            if title == "📊 Статистика еженедельных отчётов":
                data["stats_message_id"] = message.id

                await message.edit(
                    embed=embed
                )

                save_data()

                return

        message = await channel.send(
            embed=embed
        )

        data["stats_message_id"] = message.id

        save_data()

        print(
            f"✅ Создано сообщение статистики: "
            f"{message.id}"
        )

    except discord.Forbidden:
        print(
            "❌ Бот не может обновить статистику."
        )

    except discord.HTTPException as error:
        print(
            f"❌ Ошибка статистики: {error}"
        )


# ============================================================
# ЕЖЕНЕДЕЛЬНАЯ ПРОВЕРКА
# ============================================================

def get_previous_week_key() -> str:
    """Возвращает ключ завершившейся недели."""
    current_week_start = (
        now_moscow()
        - timedelta(
            days=now_moscow().weekday()
        )
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    previous_week = current_week_start - timedelta(
        days=1
    )

    return get_week_key(
        previous_week
    )


async def process_previous_week():
    """
    Выдаёт выговоры участникам,
    которые не набрали минимум.
    """
    guild = bot.get_guild(
        GUILD_ID
    )

    if guild is None:
        print(
            "❌ Сервер для недельной проверки не найден."
        )
        return

    previous_week_key = get_previous_week_key()

    processed_key = data.get(
        "last_processed_week"
    )

    if processed_key == previous_week_key:
        return

    print(
        f"📅 Проверка завершённой недели: "
        f"{get_week_display(previous_week_key)}"
    )

    mafia_members = [
        member
        for member in guild.members
        if not member.bot
        and has_mafia_role(member)
    ]

    for member in mafia_members:
        weekly_points = get_weekly_points(
            member.id,
            previous_week_key
        )

        if weekly_points >= REQUIRED_WEEKLY_POINTS:
            continue

        user_data = ensure_user_data(
            member.id
        )

        user_data["reprimands"] = int(
            user_data.get(
                "reprimands",
                0
            )
        ) + 1

        current_reprimands = user_data[
            "reprimands"
        ]

        try:
            await member.send(
                (
                    "⚠️ По итогам недели вам выдан "
                    "выговор.\n\n"
                    f"Неделя: "
                    f"**{get_week_display(previous_week_key)}**\n"
                    f"Ваш результат: "
                    f"**{weekly_points}/"
                    f"{REQUIRED_WEEKLY_POINTS}** баллов\n"
                    f"Выговоры: "
                    f"**{current_reprimands}/"
                    f"{MAX_REPRIMANDS}**"
                )
            )

        except discord.Forbidden:
            print(
                f"⚠️ Нельзя отправить выговор "
                f"{member} в ЛС."
            )

        if current_reprimands >= MAX_REPRIMANDS:
            await remove_mafia_roles(
                member,
                "Получено 5 выговоров "
                "за недельные отчёты"
            )

            try:
                await member.send(
                    (
                        "🚫 Вы получили 5 выговоров.\n\n"
                        "Роль `academy` была снята."
                    )
                )
            except discord.Forbidden:
                pass

    data["last_processed_week"] = previous_week_key

    save_data()

    await update_statistics_message()


@tasks.loop(minutes=1)
async def weekly_check_loop():
    """Проверяет, наступило ли время недельной проверки."""
    current_time = now_moscow()

    # Воскресенье 23:59 по Москве
    if current_time.weekday() != 6:
        return

    if current_time.hour != 23:
        return

    if current_time.minute != 59:
        return

    await process_previous_week()


@weekly_check_loop.before_loop
async def before_weekly_check_loop():
    await bot.wait_until_ready()


# ============================================================
# АВТООБНОВЛЕНИЕ БОТА
# ============================================================

@tasks.loop(minutes=1)
async def maintenance_loop():
    """
    Проверяет панель и статистику.
    Если сообщения удалены — создаёт их заново.
    """
    await ensure_panel_exists()
    await update_statistics_message()


@maintenance_loop.before_loop
async def before_maintenance_loop():
    await bot.wait_until_ready()


# ============================================================
# КОМАНДЫ АДМИНИСТРАТОРА
# ============================================================

@bot.tree.command(
    name="создать_панель_отчетов",
    description="Создать или восстановить панель отчётов"
)
@app_commands.guild_only()
async def create_reports_panel(
    interaction: Interaction
):
    if interaction.user.id != REVIEWER_ID:
        await interaction.response.send_message(
            "❌ У вас нет доступа к этой команде.",
            ephemeral=True
        )
        return

    await ensure_panel_exists()
    await update_statistics_message()

    await interaction.response.send_message(
        "✅ Панель отчётов и статистика проверены.",
        ephemeral=True
    )


@bot.tree.command(
    name="моя_статистика",
    description="Показать свои баллы и выговоры"
)
@app_commands.guild_only()
async def my_statistics(
    interaction: Interaction
):
    user_data = ensure_user_data(
        interaction.user.id
    )

    weekly_points = get_weekly_points(
        interaction.user.id
    )

    total_points = int(
        user_data.get(
            "total_points",
            0
        )
    )

    reprimands = int(
        user_data.get(
            "reprimands",
            0
        )
    )

    embed = discord.Embed(
        title="📊 Ваша статистика",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="📅 Текущая неделя",
        value=(
            f"{weekly_points}/"
            f"{REQUIRED_WEEKLY_POINTS} баллов"
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 Всего баллов",
        value=str(total_points),
        inline=True
    )

    embed.add_field(
        name="⚠️ Выговоры",
        value=(
            f"{reprimands}/"
            f"{MAX_REPRIMANDS}"
        ),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# СОБЫТИЕ ГОТОВНОСТИ
# ============================================================

@bot.event
async def on_ready():
    global data_loaded

    print("=" * 60)
    print(f"✅ Бот подключён: {bot.user}")
    print(f"🆔 ID: {bot.user.id}")
    print(f"🌐 Серверов: {len(bot.guilds)}")

    for guild in bot.guilds:
        print(
            f"• {guild.name} "
            f"(ID: {guild.id})"
        )

    if not data_loaded:
        load_data()
        data_loaded = True

    if not weekly_check_loop.is_running():
        weekly_check_loop.start()

    if not maintenance_loop.is_running():
        maintenance_loop.start()

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="за отчётами мафии"
        )
    )

    await asyncio.sleep(2)

    await ensure_panel_exists()
    await update_statistics_message()

    print("=" * 60)


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("🚀 Запуск бота...")
    print(
        f"🔑 Токен найден: {bool(TOKEN)}"
    )

    try:
        bot.run(TOKEN)

    except discord.LoginFailure:
        print(
            "❌ Неверный токен Discord-бота."
        )

    except discord.PrivilegedIntentsRequired:
        print(
            "❌ Не включены Privileged Gateway Intents.\n"
            "Включи Server Members Intent и "
            "Message Content Intent."
        )

    except Exception as error:
        print(
            f"❌ Критическая ошибка запуска: "
            f"{error}"
        )