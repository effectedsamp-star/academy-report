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

GUILD_ID = 1534179608390406308

REPORTS_CHANNEL_ID = 1552806315472982086
STATS_CHANNEL_ID = 1552806315472982086

# Канал, серверы из которого разрешены для отчётов о снятии выговора
REPRIMAND_SERVERS_CHANNEL_ID = 1540010365839089775

REVIEWER_ID = 1416863224430596107

MAFIA_ROLE_NAME = "academy"

ROLES_TO_REMOVE_AFTER_FIVE = [
    "academy"
]

REQUIRED_WEEKLY_POINTS = 5
MAX_REPRIMANDS = 5

# Одна стрела равна половине балла
POINTS_PER_SHOOTOUT = 0.5

DATA_FILE = "mafia_reports_data.json"

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

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

data = {
    "users": {},
    "weekly_points": {},
    "reports": {},
    "panel_message_id": None,
    "stats_message_id": None,
    "last_processed_week": None
}

data_loaded = False


# ============================================================
# СОХРАНЕНИЕ И ЗАГРУЗКА
# ============================================================

def save_data():
    """Сохраняет данные в JSON-файл."""
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
                "Корень JSON должен быть объектом."
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
            ),
            "last_processed_week": loaded_data.get(
                "last_processed_week"
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

    except json.JSONDecodeError as error:
        print(
            f"❌ Ошибка JSON-файла: {error}"
        )

    except ValueError as error:
        print(
            f"❌ Ошибка структуры данных: {error}"
        )

    except OSError as error:
        print(
            f"❌ Ошибка загрузки данных: {error}"
        )


def ensure_user_data(user_id: int):
    """Создаёт профиль пользователя, если его нет."""
    user_key = str(user_id)

    if user_key not in data["users"]:
        data["users"][user_key] = {
            "total_points": 0.0,
            "reprimands": 0,
            "reprimand_removal_reports": 0
        }

    user_data = data["users"][user_key]

    if "total_points" not in user_data:
        user_data["total_points"] = 0.0

    if "reprimands" not in user_data:
        user_data["reprimands"] = 0

    if "reprimand_removal_reports" not in user_data:
        user_data["reprimand_removal_reports"] = 0

    return user_data


# ============================================================
# РАБОТА С БАЛЛАМИ
# ============================================================

def format_points(points: float) -> str:
    """Красиво отображает целые и дробные баллы."""
    points = float(points)

    if points.is_integer():
        return str(int(points))

    return f"{points:.1f}"


def shoots_to_points(shoots: int) -> float:
    """Переводит количество стрел в баллы."""
    return shoots * POINTS_PER_SHOOTOUT


def get_weekly_points(
    user_id: int,
    week_key: str | None = None
) -> float:
    """Возвращает баллы пользователя за неделю."""
    if week_key is None:
        week_key = get_week_key()

    week_data = data["weekly_points"].get(
        week_key,
        {}
    )

    return float(
        week_data.get(
            str(user_id),
            0
        )
    )


def add_weekly_points(
    user_id: int,
    points: float,
    week_key: str | None = None
):
    """Добавляет баллы за неделю и в общую статистику."""
    if week_key is None:
        week_key = get_week_key()

    if week_key not in data["weekly_points"]:
        data["weekly_points"][week_key] = {}

    user_key = str(user_id)

    old_weekly_points = float(
        data["weekly_points"][week_key].get(
            user_key,
            0
        )
    )

    data["weekly_points"][week_key][user_key] = (
        old_weekly_points + points
    )

    user_data = ensure_user_data(user_id)

    user_data["total_points"] = float(
        user_data.get(
            "total_points",
            0
        )
    ) + points


# ============================================================
# РУЧНЫЕ ОПЕРАЦИИ С БАЛЛАМИ И ВЫГОВОРАМИ
# ============================================================

def change_user_points(user_id: int, points: float, week_key: str | None = None):
    """Изменяет общий и недельный баланс; баланс может быть отрицательным."""
    if week_key is None:
        week_key = get_week_key()
    if week_key not in data["weekly_points"]:
        data["weekly_points"][week_key] = {}
    user_key = str(user_id)
    data["weekly_points"][week_key][user_key] = (
        float(data["weekly_points"][week_key].get(user_key, 0)) + points
    )
    user_data = ensure_user_data(user_id)
    user_data["total_points"] = float(user_data.get("total_points", 0)) + points
    return user_data["total_points"], data["weekly_points"][week_key][user_key]


def add_reprimand(user_id: int, amount: int = 1) -> int:
    user_data = ensure_user_data(user_id)
    user_data["reprimands"] = max(0, int(user_data.get("reprimands", 0)) + amount)
    return user_data["reprimands"]


def remove_reprimand(user_id: int, amount: int = 1) -> int:
    user_data = ensure_user_data(user_id)
    user_data["reprimands"] = max(0, int(user_data.get("reprimands", 0)) - amount)
    return user_data["reprimands"]


# ============================================================
# ВРЕМЯ И НЕДЕЛИ
# ============================================================

def now_moscow() -> datetime:
    """Возвращает текущее время по Москве."""
    return datetime.now(MOSCOW_TZ)


def get_week_key(
    moment: datetime | None = None
) -> str:
    """
    Возвращает ключ отчётной недели.

    Неделя:
    понедельник 00:00 —
    воскресенье 23:59 по Москве.
    """
    if moment is None:
        moment = now_moscow()

    moment = moment.astimezone(MOSCOW_TZ)

    monday = (
        moment
        - timedelta(days=moment.weekday())
    ).replace(
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
    """Возвращает начало и конец недели."""
    if week_key is None:
        week_key = get_week_key()

    try:
        monday_text, sunday_text = week_key.split("_")

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
    """Красивое отображение отчётной недели."""
    monday, sunday = get_week_dates(week_key)

    return (
        f"{monday.strftime('%d.%m.%Y')} — "
        f"{sunday.strftime('%d.%m.%Y')}"
    )


def get_previous_week_key() -> str:
    """Возвращает ключ завершившейся недели."""
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

    previous_sunday = current_monday - timedelta(
        days=1
    )

    return get_week_key(previous_sunday)


# ============================================================
# РОЛИ
# ============================================================

def has_mafia_role(
    member: discord.Member
) -> bool:
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
    """Снимает роли после пяти выговоров."""
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

    if member.guild.me is None:
        print(
            "❌ Не удалось определить бота "
            "на сервере."
        )
        return

    for role in roles_to_remove:
        if role >= member.guild.me.top_role:
            print(
                f"❌ Роль {role.name} находится "
                "выше роли бота."
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
            "Проверь Manage Roles."
        )

    except discord.HTTPException as error:
        print(
            f"❌ Ошибка снятия ролей: {error}"
        )


# ============================================================
# ОТЧЁТЫ
# ============================================================

def is_allowed_image(
    attachment: discord.Attachment
) -> bool:
    """Проверяет, является ли вложение изображением."""
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
    """Ищет отчёт пользователя на проверке."""
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


# ============================================================
# EMBED УВЕДОМЛЕНИЙ
# ============================================================

async def send_report_pending_dm(
    user: discord.User,
    report: dict
):
    """Уведомление об отправке отчёта."""
    requested_shoots = int(
        report.get("requested_shoots", 0)
    )

    calculated_points = float(
        report.get("calculated_points", 0)
    )

    embed = discord.Embed(
        title="📨 Отчёт отправлен на проверку",
        description=(
            "Ваш отчёт успешно получен и передан "
            "проверяющему."
        ),
        color=discord.Color.orange(),
        timestamp=now_moscow()
    )

    embed.add_field(
        name="🎯 Заявлено стрел",
        value=str(requested_shoots),
        inline=True
    )

    embed.add_field(
        name="💰 Возможное начисление",
        value=(
            f"**{format_points(calculated_points)} балла**"
        ),
        inline=True
    )

    embed.add_field(
        name="📅 Отчётная неделя",
        value=get_week_display(
            report.get("week_key")
        ),
        inline=False
    )

    embed.add_field(
        name="⏳ Статус",
        value="Ожидает проверки администратора",
        inline=False
    )

    embed.set_footer(
        text=f"ID отчёта: {report.get('report_id')}"
    )

    await user.send(embed=embed)


async def send_report_accepted_dm(
    user: discord.User,
    report: dict
):
    """Уведомление о начислении баллов."""
    requested_shoots = int(
        report.get("requested_shoots", 0)
    )

    accepted_points = float(
        report.get("accepted_points", 0)
    )

    weekly_points = get_weekly_points(
        int(report["user_id"]),
        report.get("week_key")
    )

    embed = discord.Embed(
        title="✅ Баллы начислены",
        description=(
            "Ваш отчёт был проверен и одобрен.\n\n"
            "Указанные баллы добавлены "
            "в вашу статистику."
        ),
        color=discord.Color.green(),
        timestamp=now_moscow()
    )

    embed.add_field(
        name="🎯 Стрелы в отчёте",
        value=str(requested_shoots),
        inline=True
    )

    embed.add_field(
        name="💰 Начислено",
        value=(
            f"**{format_points(accepted_points)} балла**"
        ),
        inline=True
    )

    embed.add_field(
        name="📊 Баллы за неделю",
        value=(
            f"**{format_points(weekly_points)}/"
            f"{format_points(REQUIRED_WEEKLY_POINTS)}**"
        ),
        inline=True
    )

    embed.add_field(
        name="📅 Отчётная неделя",
        value=get_week_display(
            report.get("week_key")
        ),
        inline=False
    )

    embed.add_field(
        name="📌 Итог",
        value="Отчёт принят, баллы сохранены.",
        inline=False
    )

    embed.set_footer(
        text=f"ID отчёта: {report.get('report_id')}"
    )

    await user.send(embed=embed)


async def send_report_rejected_dm(
    user: discord.User,
    report: dict
):
    """Уведомление об отказе в начислении баллов."""
    reason = str(
        report.get("reason", "")
    ).strip()

    embed = discord.Embed(
        title="❌ В начислении баллов отказано",
        description=(
            "Ваш отчёт был проверен, "
            "но баллы не были начислены."
        ),
        color=discord.Color.red(),
        timestamp=now_moscow()
    )

    embed.add_field(
        name="📅 Отчётная неделя",
        value=get_week_display(
            report.get("week_key")
        ),
        inline=False
    )

    embed.add_field(
        name="📝 Причина отказа",
        value=reason or "Причина не указана",
        inline=False
    )

    embed.add_field(
        name="📌 Итог",
        value=(
            "Исправьте недочёты и отправьте "
            "новый отчёт."
        ),
        inline=False
    )

    embed.set_footer(
        text=f"ID отчёта: {report.get('report_id')}"
    )

    await user.send(embed=embed)


# ============================================================
# EMBED ОТЧЁТА ДЛЯ ПРОВЕРЯЮЩЕГО
# ============================================================

def create_report_embed(
    report: dict,
    member: discord.Member | None = None
) -> discord.Embed:
    """Создаёт Embed заявки."""
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

    report_user_id = int(
        report["user_id"]
    )

    report_week_key = report.get(
        "week_key"
    )

    weekly_points = get_weekly_points(
        report_user_id,
        report_week_key
    )

    user_data = ensure_user_data(
        report_user_id
    )

    reprimands = int(
        user_data.get(
            "reprimands",
            0
        )
    )

    requested_shoots = int(
        report.get(
            "requested_shoots",
            0
        )
    )

    calculated_points = shoots_to_points(
        requested_shoots
    )

    status_color = discord.Color.orange()

    if status == "accepted":
        status_color = discord.Color.green()

    elif status == "rejected":
        status_color = discord.Color.red()

    embed = discord.Embed(
        title="📨 Недельный отчёт",
        description=(
            "Проверьте скриншоты или ссылку "
            "на скриншоты и решите, начислять ли баллы."
        ),
        color=status_color
    )

    embed.add_field(
        name="👤 Участник",
        value=user_text,
        inline=False
    )

    embed.add_field(
        name="📅 Отчётная неделя",
        value=get_week_display(
            report_week_key
        ),
        inline=True
    )

    embed.add_field(
        name="🎯 Заявлено стрел",
        value=str(requested_shoots),
        inline=True
    )

    embed.add_field(
        name="💰 По расчёту",
        value=(
            f"{requested_shoots} × "
            f"{format_points(POINTS_PER_SHOOTOUT)} "
            f"= **{format_points(calculated_points)} балла**"
        ),
        inline=True
    )

    embed.add_field(
        name="📊 Баллы за неделю",
        value=(
            f"{format_points(weekly_points)}/"
            f"{format_points(REQUIRED_WEEKLY_POINTS)}"
        ),
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

    embed.add_field(
        name="📌 Статус",
        value=status_text,
        inline=True
    )

    comment = str(
        report.get(
            "comment",
            ""
        )
    ).strip()

    embed.add_field(
        name="💬 Ссылка или комментарий",
        value=(
            comment[:1024]
            if comment
            else "Не указан"
        ),
        inline=False
    )

    reason = str(
        report.get(
            "reason",
            ""
        )
    ).strip()

    if reason:
        embed.add_field(
            name="📝 Причина отказа",
            value=reason[:1024],
            inline=False
        )

    embed.set_footer(
        text=(
            f"ID отчёта: "
            f"{report.get('report_id')}"
        )
    )

    return embed


# ============================================================
# EMBED СТАТИСТИКИ
# ============================================================

def create_statistics_embed(
    guild: discord.Guild
) -> discord.Embed:
    """Создаёт таблицу статистики."""
    week_key = get_week_key()

    embed = discord.Embed(
        title="📊 Статистика еженедельных отчётов",
        description=(
            f"Текущая неделя: "
            f"**{get_week_display(week_key)}**\n"
            f"Минимум: "
            f"**{format_points(REQUIRED_WEEKLY_POINTS)} "
            f"баллов**\n"
            f"Расчёт: "
            f"**1 стрела = "
            f"{format_points(POINTS_PER_SHOOTOUT)} балла**"
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
                f"Участники с ролью "
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

        total_points = float(
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
            f"**{format_points(weekly_points)}/"
            f"{format_points(REQUIRED_WEEKLY_POINTS)}** "
            f"· Всего: **{format_points(total_points)}** "
            f"· Выговоры: **{reprimands}/"
            f"{MAX_REPRIMANDS}**"
        )

    chunks = []
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 2 > 1000:
            chunks.append(
                current_chunk
            )
            current_chunk = ""

        current_chunk += line + "\n\n"

    if current_chunk:
        chunks.append(
            current_chunk
        )

    for index, chunk in enumerate(
        chunks
    ):
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
            "Таблица обновляется автоматически"
        )
    )

    return embed


# ============================================================
# УДАЛЕНИЕ СООБЩЕНИЯ СО СКРИНШОТАМИ
# ============================================================

async def delete_attachment_message(
    message: discord.Message
):
    """Удаляет сообщение пользователя со скриншотами."""
    try:
        await message.delete()
        print(
            f"🗑️ Удалено сообщение "
            f"со скриншотами: {message.id}"
        )

    except discord.Forbidden:
        print(
            "❌ Нет права удалять сообщения "
            "в канале отчётов."
        )

    except discord.NotFound:
        print(
            "⚠️ Сообщение со скриншотами "
            "уже удалено."
        )

    except discord.HTTPException as error:
        print(
            f"❌ Ошибка удаления сообщения: {error}"
        )


# ============================================================
# MODAL ОТПРАВКИ ОТЧЁТА
# ============================================================

class ReportModal(ui.Modal):
    def __init__(
        self,
        member: discord.Member
    ):
        super().__init__(
            title="Подача недельного отчёта"
        )

        self.member = member

        self.shoots_input = ui.TextInput(
            label="Количество стрел",
            placeholder="Например: 10",
            min_length=1,
            max_length=4,
            required=True
        )

        self.comment_input = ui.TextInput(
            label="Ссылка на скриншоты или комментарий",
            placeholder="Вставьте ссылку или напишите позитивный комментарий",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=False
        )

        self.add_item(
            self.shoots_input
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

        if not isinstance(
            self.member,
            discord.Member
        ):
            await interaction.response.send_message(
                "❌ Не удалось определить участника.",
                ephemeral=True
            )
            return

        if not has_mafia_role(self.member):
            await interaction.response.send_message(
                f"❌ У вас нет роли "
                f"`{MAFIA_ROLE_NAME}`.",
                ephemeral=True
            )
            return

        try:
            requested_shoots = int(
                str(
                    self.shoots_input.value
                ).strip()
            )

        except ValueError:
            await interaction.response.send_message(
                "❌ Количество стрел должно быть числом.",
                ephemeral=True
            )
            return

        if requested_shoots <= 0:
            await interaction.response.send_message(
                "❌ Количество стрел должно быть "
                "больше нуля.",
                ephemeral=True
            )
            return

        if requested_shoots > 1000:
            await interaction.response.send_message(
                "❌ Нельзя указать больше 1000 стрел.",
                ephemeral=True
            )
            return

        week_key = get_week_key()

        # Разрешены повторные отчёты за неделю.
        # Запрещён только второй отчёт,
        # пока предыдущий находится на проверке.
        if get_pending_report_for_user(
            self.member.id,
            week_key
        ):
            await interaction.response.send_message(
                (
                    "❌ У вас уже есть отчёт "
                    "на проверке.\n"
                    "Дождитесь его обработки, после чего "
                    "сможете отправить следующий."
                ),
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            (
                "📎 Теперь отправьте в этот канал "
                "сообщение со скриншотами отчёта "
                "или укажите ссылку на скриншоты "
                "в комментарии.\n\n"
                f"Заявлено стрел: **{requested_shoots}**\n"
                f"Расчёт: **"
                f"{format_points(shoots_to_points(requested_shoots))} "
                f"балла**\n\n"
                "Если прикрепляете скриншоты, "
                "их можно отправить одним сообщением."
            ),
            ephemeral=True
        )

        comment = str(
            self.comment_input.value
        ).strip()

        # Если в комментарии есть ссылка,
        # сообщение со скриншотами можно не отправлять
        has_link_in_comment = (
            "http://" in comment.lower()
            or "https://" in comment.lower()
            or "www." in comment.lower()
        )

        attachment_message = None
        image_attachments = []

        if not has_link_in_comment:
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
                        (
                            "⌛ Время ожидания скриншотов "
                            "истекло.\n"
                            "Отчёт не был создан."
                        )
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
                try:
                    await self.member.send(
                        (
                            "❌ Отчёт не принят.\n"
                            "В сообщении не найдено "
                            "изображений."
                        )
                    )

                except discord.Forbidden:
                    pass

                return

        report_id = get_report_id()

        calculated_points = shoots_to_points(
            requested_shoots
        )

        report = {
            "report_id": report_id,
            "user_id": self.member.id,
            "guild_id": guild.id,
            "week_key": week_key,
            "requested_shoots": requested_shoots,
            "calculated_points": calculated_points,
            "accepted_points": 0.0,
            "comment": comment,
            "attachment_urls": [
                attachment.url
                for attachment in image_attachments
            ],
            "source_message_id": (
                attachment_message.id
                if attachment_message
                else None
            ),
            "status": "pending",
            "reviewer_id": None,
            "reason": "",
            "created_at": now_moscow().isoformat()
        }

        data["reports"][report_id] = report

        save_data()

        reviewer = bot.get_user(
            REVIEWER_ID
        )

        if reviewer is None:
            try:
                reviewer = await bot.fetch_user(
                    REVIEWER_ID
                )

            except discord.HTTPException:
                reviewer = None

        if reviewer is None:
            await interaction.followup.send(
                (
                    "⚠️ Отчёт сохранён, но "
                    "проверяющий не найден."
                ),
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

            # Отправляем скриншоты проверяющему
            # настоящими файлами
            for attachment in image_attachments:
                try:
                    image_file = await attachment.to_file(
                        spoiler=False
                    )

                    await reviewer.send(
                        file=image_file
                    )

                except discord.HTTPException as error:
                    print(
                        f"❌ Не удалось отправить "
                        f"скриншот проверяющему: {error}"
                    )

            # После копирования удаляем сообщение
            # со скриншотами из общего канала
            if attachment_message is not None:
                await delete_attachment_message(
                    attachment_message
                )

            try:
                await send_report_pending_dm(
                    self.member,
                    report
                )

            except discord.Forbidden:
                print(
                    "⚠️ Нельзя отправить уведомление "
                    "о подаче отчёта в ЛС."
                )

            except discord.HTTPException as error:
                print(
                    f"⚠️ Ошибка уведомления "
                    f"о подаче отчёта: {error}"
                )

            await update_statistics_message()

        except discord.Forbidden:
            await interaction.followup.send(
                (
                    "❌ Не удалось отправить отчёт "
                    "проверяющему в личные сообщения.\n"
                    "Проверьте, открыты ли ЛС."
                ),
                ephemeral=True
            )

        except discord.HTTPException as error:
            print(
                f"❌ Ошибка отправки отчёта: {error}"
            )


class ReprimandRemovalModal(ui.Modal):
    def __init__(self, member: discord.Member):
        super().__init__(title="Снять выговор")
        self.member = member
        self.comment_input = ui.TextInput(
            label="Ссылка на скриншоты или комментарий",
            placeholder="Вставьте ссылку или опишите выполненное условие",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True
        )
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: Interaction):
        if interaction.guild is None or not has_mafia_role(self.member):
            await interaction.response.send_message(
                "❌ Отправка доступна только участнику академки.",
                ephemeral=True
            )
            return

        user_data = ensure_user_data(self.member.id)
        if float(user_data.get("reprimands", 0)) <= 0:
            await interaction.response.send_message(
                "✅ У вас нет выговоров для снятия.",
                ephemeral=True
            )
            return

        comment = str(self.comment_input.value).strip()
        report_id = get_report_id()
        report = {
            "report_id": report_id,
            "user_id": self.member.id,
            "guild_id": interaction.guild.id,
            "week_key": get_week_key(),
            "comment": comment,
            "status": "pending",
            "report_type": "reprimand_removal",
            "created_at": now_moscow().isoformat(),
            "reviewer_id": None,
            "removal_amount": 0.0
        }
        data["reports"][report_id] = report
        save_data()

        reviewer = bot.get_user(REVIEWER_ID)
        if reviewer is None:
            try:
                reviewer = await bot.fetch_user(REVIEWER_ID)
            except discord.HTTPException:
                reviewer = None

        if reviewer is None:
            data["reports"].pop(report_id, None)
            save_data()
            await interaction.response.send_message(
                "❌ Не удалось найти проверяющего. Попробуйте позже.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="⚠️ Заявка на снятие выговора",
            color=discord.Color.orange(),
            timestamp=now_moscow()
        )
        embed.add_field(
            name="👤 Участник",
            value=f"{self.member.mention} (`{self.member.id}`)",
            inline=False
        )
        embed.add_field(
            name="💬 Ссылка или комментарий",
            value=comment[:1024] if comment else "Не указан",
            inline=False
        )
        embed.add_field(
            name="📌 Как снять выговор",
            value=(
                "Выиграть 3 стрелы: **-1 выговор**\n"
                "Выиграть клатч 1 в 2: **-1 выговор**\n"
                "Выиграть клатч 1 в 3+: **-2 выговора**\n"
                "Простоять до конца стрелы (0:00): **-0.5 выговора**"
            ),
            inline=False
        )
        embed.set_footer(text=f"ID заявки: {report_id}")

        try:
            await reviewer.send(
                embed=embed,
                view=ReprimandRemovalReviewView(report_id)
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"❌ Ошибка отправки заявки проверяющему: {error}")
            data["reports"].pop(report_id, None)
            save_data()
            await interaction.response.send_message(
                "❌ Не удалось отправить заявку проверяющему.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "✅ Заявка на снятие выговора отправлена проверяющему.",
            ephemeral=True
        )


class ReprimandRemovalReviewView(ui.View):
    def __init__(self, report_id: str):
        super().__init__(timeout=None)
        self.report_id = report_id

    @ui.button(
        label="Снять 1",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="mafia_reprimand_approve_1"
    )
    async def approve_one(self, interaction: Interaction, button: ui.Button):
        await self.process_approval(interaction, 1.0)

    @ui.button(
        label="Снять 2",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="mafia_reprimand_approve_2"
    )
    async def approve_two(self, interaction: Interaction, button: ui.Button):
        await self.process_approval(interaction, 2.0)

    @ui.button(
        label="Снять 0.5",
        emoji="➗",
        style=discord.ButtonStyle.secondary,
        custom_id="mafia_reprimand_approve_half"
    )
    async def approve_half(self, interaction: Interaction, button: ui.Button):
        await self.process_approval(interaction, 0.5)

    @ui.button(
        label="Отклонить",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="mafia_reprimand_reject"
    )
    async def reject(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != REVIEWER_ID:
            await interaction.response.send_message("❌ У вас нет доступа.", ephemeral=True)
            return
        report = data["reports"].get(self.report_id)
        if not report or report.get("status") != "pending":
            await interaction.response.send_message("❌ Заявка уже обработана или не найдена.", ephemeral=True)
            return
        report["status"] = "rejected"
        report["reviewer_id"] = interaction.user.id
        report["reviewed_at"] = now_moscow().isoformat()
        save_data()
        await interaction.response.edit_message(
            content="❌ Заявка отклонена.",
            embed=None,
            view=None
        )

    async def process_approval(self, interaction: Interaction, amount: float):
        if interaction.user.id != REVIEWER_ID:
            await interaction.response.send_message("❌ У вас нет доступа.", ephemeral=True)
            return
        report = data["reports"].get(self.report_id)
        if not report or report.get("status") != "pending":
            await interaction.response.send_message("❌ Заявка уже обработана или не найдена.", ephemeral=True)
            return

        user_id = int(report["user_id"])
        user_data = ensure_user_data(user_id)
        before = float(user_data.get("reprimands", 0))
        removed = min(amount, before)
        remaining = max(0.0, before - removed)
        user_data["reprimands"] = remaining

        report["status"] = "accepted"
        report["reviewer_id"] = interaction.user.id
        report["reviewed_at"] = now_moscow().isoformat()
        report["removal_amount"] = removed
        save_data()

        await interaction.response.edit_message(
            content=(
                f"✅ Снято: {format_points(removed)}. "
                f"Осталось: {format_points(remaining)}/{MAX_REPRIMANDS}."
            ),
            embed=None,
            view=None
        )
        await update_statistics_message()


# ============================================================
# ПАНЕЛЬ УЧАСТНИКА
# ============================================================

class SubmitReportView(ui.View):
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

        if not isinstance(
            member,
            discord.Member
        ):
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

        # Проверяем только активный отчёт
        # на проверке. Принятые отчёты не блокируют
        # повторную подачу.
        if get_pending_report_for_user(
            member.id,
            week_key
        ):
            await interaction.response.send_message(
                (
                    "❌ У вас уже есть отчёт "
                    "на проверке.\n"
                    "После его обработки можно будет "
                    "отправить следующий."
                ),
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            ReportModal(member)
        )

    @ui.button(
        label="Снять выговор",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        custom_id="mafia_remove_reprimand_button"
    )
    async def remove_reprimand_button(self, interaction: Interaction, button: ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member) or not has_mafia_role(member):
            await interaction.response.send_message(f"❌ Для снятия выговора нужна роль `{MAFIA_ROLE_NAME}`.", ephemeral=True)
            return
        if int(ensure_user_data(member.id).get("reprimands", 0)) <= 0:
            await interaction.response.send_message("✅ У вас нет выговоров для снятия.", ephemeral=True)
            return
        await interaction.response.send_modal(ReprimandRemovalModal(member))

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

        total_points = float(
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
                f"{format_points(weekly_points)}/"
                f"{format_points(REQUIRED_WEEKLY_POINTS)}"
                " баллов"
            ),
            inline=False
        )

        embed.add_field(
            name="🎯 Стрелы",
            value=(
                f"1 стрела = "
                f"{format_points(POINTS_PER_SHOOTOUT)} "
                "балла"
            ),
            inline=False
        )

        embed.add_field(
            name="🏆 Всего баллов",
            value=format_points(total_points),
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
# ПРОВЕРКА ОТЧЁТА
# ============================================================

class ReportReviewView(ui.View):
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

        requested_shoots = int(
            report.get(
                "requested_shoots",
                0
            )
        )

        points = shoots_to_points(
            requested_shoots
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

        guild = bot.get_guild(
            int(report["guild_id"])
        )

        member = None

        if guild:
            member = guild.get_member(
                int(report["user_id"])
            )

        result_embed = create_report_embed(
            report,
            member
        )

        result_embed.add_field(
            name="✅ Начислено",
            value=(
                f"{format_points(points)} балла"
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

            await send_report_accepted_dm(
                user,
                report
            )

        except discord.Forbidden:
            print(
                "⚠️ Нельзя отправить результат "
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
                "не видно дату"
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
                "❌ У вас нет доступа.",
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

        guild = bot.get_guild(
            int(report["guild_id"])
        )

        member = None

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

            await send_report_rejected_dm(
                user,
                report
            )

        except discord.Forbidden:
            print(
                "⚠️ Нельзя отправить отказ "
                "игроку в ЛС."
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
    """Создаёт панель подачи отчётов."""
    embed = discord.Embed(
        title="📨 Еженедельные отчёты мафии",
        description=(
            "Каждую неделю участники мафии должны "
            "набрать минимум **5 баллов**.\n\n"

            "**Расчёт баллов:**\n"
            "🎯 **1 стрела = 0.5 балла**\n"
            "🎯 **2 стрелы = 1 балл**\n"
            "🎯 **10 стрел = 5 баллов**\n\n"

            "**Как подать отчёт:**\n"
            "1. Нажмите `📨 Подать отчёт`.\n"
            "2. Укажите количество стрел.\n"
            "3. В комментарии можно написать почему ваш отчет должен быть проверен.\n"
            "4. Отправьте скриншоты в этот канал "
            "или прикрепите ссылку в комментарии "
            "отчёта на ваши скрины.\n"
            "5. Дождитесь проверки администратора.\n\n"

            "За неделю в обязательном порядке нужно давать отчеты о вашей работе.\n"
            "При этом если вы не набираете нужное "
            "количество баллов за неделю вам дается выговор.\n\n"

            "Если за неделю набрано меньше "
            "**5 баллов**, участник получает "
            "один выговор.\n"
            "После **5 выговоров** вы покидаете нашу семью автоматически.\n\n"
            "**Как снять выговор:**\n"
            "Выиграть 3 стрелы: **-1 выговор**\n"
            "Выиграть клатч 1 в 2: **-1 выговор**\n"
            "Выиграть клатч 1 в 3+: **-2 выговора**\n"
            "Простоять до конца стрелы (0:00): **-0.5 выговора**\n\n"
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
            "Отчёты проверяются администратором вручную"
        )
    )

    return embed


# ============================================================
# ПОДДЕРЖАНИЕ ПАНЕЛИ
# ============================================================

async def ensure_panel_exists():
    """Проверяет и восстанавливает панель отчётов."""
    channel = bot.get_channel(
        REPORTS_CHANNEL_ID
    )

    if channel is None:
        print(
            "❌ Канал отчётов не найден."
        )
        return

    if not isinstance(
        channel,
        discord.TextChannel
    ):
        print(
            "❌ Канал отчётов должен быть текстовым."
        )
        return

    embed = create_panel_embed()

    saved_message_id = data.get(
        "panel_message_id"
    )

    if saved_message_id:
        try:
            message = await channel.fetch_message(
                int(saved_message_id)
            )

            await message.edit(
                embed=embed,
                view=SubmitReportView()
            )

            return

        except discord.NotFound:
            print(
                "⚠️ Старая панель была удалена."
            )

        except discord.Forbidden:
            print(
                "❌ Нет доступа к старой панели."
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

            if message.embeds[0].title == (
                "📨 Еженедельные отчёты мафии"
            ):
                data["panel_message_id"] = message.id

                await message.edit(
                    embed=embed,
                    view=SubmitReportView()
                )

                save_data()

                print(
                    "✅ Найдена старая панель."
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
            f"✅ Создана новая панель: "
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
# ПОДДЕРЖАНИЕ СТАТИСТИКИ
# ============================================================

async def update_statistics_message():
    """Создаёт или обновляет сообщение статистики."""
    guild = bot.get_guild(
        GUILD_ID
    )

    if guild is None:
        print(
            "❌ Сервер не найден."
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

    if not isinstance(
        channel,
        discord.TextChannel
    ):
        return

    embed = create_statistics_embed(
        guild
    )

    saved_message_id = data.get(
        "stats_message_id"
    )

    try:
        if saved_message_id:
            try:
                message = await channel.fetch_message(
                    int(saved_message_id)
                )

                await message.edit(
                    embed=embed
                )

                return

            except discord.NotFound:
                print(
                    "⚠️ Старое сообщение статистики "
                    "удалено."
                )

        async for message in channel.history(
            limit=100
        ):
            if message.author != bot.user:
                continue

            if not message.embeds:
                continue

            if message.embeds[0].title == (
                "📊 Статистика еженедельных отчётов"
            ):
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
# НЕДЕЛЬНАЯ ПРОВЕРКА
# ============================================================

async def process_previous_week():
    """
    Проверяет завершившуюся неделю.

    Если участник набрал меньше 5 баллов,
    ему добавляется один выговор.
    """
    guild = bot.get_guild(
        GUILD_ID
    )

    if guild is None:
        print(
            "❌ Сервер для проверки не найден."
        )
        return

    previous_week_key = get_previous_week_key()

    if data.get("last_processed_week") == (
        previous_week_key
    ):
        return

    print(
        f"📅 Проверка недели: "
        f"{get_week_display(previous_week_key)}"
    )

    members = [
        member
        for member in guild.members
        if not member.bot
        and has_mafia_role(member)
    ]

    for member in members:
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

        reprimands = user_data["reprimands"]

        try:
            await member.send(
                (
                    "⚠️ По итогам недели вам выдан "
                    "выговор.\n\n"
                    f"Неделя: "
                    f"**{get_week_display(previous_week_key)}**\n"
                    f"Ваш результат: "
                    f"**{format_points(weekly_points)}/"
                    f"{format_points(REQUIRED_WEEKLY_POINTS)}**\n"
                    f"Выговоры: "
                    f"**{reprimands}/"
                    f"{MAX_REPRIMANDS}**"
                )
            )

        except discord.Forbidden:
            print(
                f"⚠️ Нельзя отправить выговор "
                f"{member} в ЛС."
            )

        if reprimands >= MAX_REPRIMANDS:
            await remove_mafia_roles(
                member,
                (
                    "Получено 5 выговоров "
                    "за недельные отчёты"
                )
            )

            try:
                await member.send(
                    (
                        "🚫 Вы получили 5 выговоров.\n\n"
                        f"Роль `{MAFIA_ROLE_NAME}` "
                        "была снята."
                    )
                )

            except discord.Forbidden:
                pass

    data["last_processed_week"] = (
        previous_week_key
    )

    save_data()

    await update_statistics_message()


@tasks.loop(minutes=1)
async def weekly_check_loop():
    """Запускает проверку в воскресенье в 23:59 МСК."""
    current_time = now_moscow()

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
# АВТООБНОВЛЕНИЕ
# ============================================================

@tasks.loop(minutes=1)
async def maintenance_loop():
    """Проверяет панель и статистику."""
    await ensure_panel_exists()
    await update_statistics_message()


@maintenance_loop.before_loop
async def before_maintenance_loop():
    await bot.wait_until_ready()


# ============================================================
# КЛАСС БОТА
# ============================================================

class AcademyReportBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(
            SubmitReportView()
        )

        try:
            synced_commands = await self.tree.sync()

            print(
                f"📋 Синхронизировано команд: "
                f"{len(synced_commands)}"
            )

        except discord.HTTPException as error:
            print(
                f"❌ Ошибка синхронизации команд: "
                f"{error}"
            )


bot = AcademyReportBot(
    command_prefix="!",
    intents=INTENTS
)


# ============================================================
# АДМИНИСТРАТИВНЫЕ КОМАНДЫ
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

    total_points = float(
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
            f"{format_points(weekly_points)}/"
            f"{format_points(REQUIRED_WEEKLY_POINTS)} "
            "баллов"
        ),
        inline=False
    )

    embed.add_field(
        name="🎯 Расчёт",
        value=(
            f"1 стрела = "
            f"{format_points(POINTS_PER_SHOOTOUT)} "
            "балла"
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 Всего баллов",
        value=format_points(total_points),
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


def is_admin_user(interaction: Interaction) -> bool:
    return interaction.user.id == REVIEWER_ID or (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild)


@bot.tree.command(name="addbal", description="Добавить баллы участнику академки")
@app_commands.guild_only()
@app_commands.describe(user="Участник", points="Количество баллов")
async def addbal(interaction: Interaction, user: discord.Member, points: float):
    if not is_admin_user(interaction):
        await interaction.response.send_message("❌ У вас нет доступа.", ephemeral=True); return
    if points <= 0:
        await interaction.response.send_message("❌ Укажите положительное число.", ephemeral=True); return
    total, weekly = change_user_points(user.id, points)
    save_data(); await update_statistics_message()
    try: await user.send(f"✅ Вам выдали +{format_points(points)} баллов.\nВаши баллы: {format_points(total)}/{format_points(REQUIRED_WEEKLY_POINTS)} баллов.")
    except discord.HTTPException: pass
    await interaction.response.send_message(f"✅ Выдано {format_points(points)} баллов пользователю {user.mention}. Баланс: {format_points(total)}.", ephemeral=True)


@bot.tree.command(name="unbal", description="Снять баллы с участника академки")
@app_commands.guild_only()
@app_commands.describe(user="Участник", points="Количество снимаемых баллов")
async def unbal(interaction: Interaction, user: discord.Member, points: float):
    if not is_admin_user(interaction):
        await interaction.response.send_message("❌ У вас нет доступа.", ephemeral=True); return
    if points <= 0:
        await interaction.response.send_message("❌ Укажите положительное число.", ephemeral=True); return
    total, weekly = change_user_points(user.id, -points)
    save_data(); await update_statistics_message()
    try: await user.send(f"⚠️ Вам сняли {format_points(points)} баллов.\nВаши баллы: {format_points(total)}")
    except discord.HTTPException: pass
    await interaction.response.send_message(f"✅ Снято {format_points(points)} баллов у {user.mention}. Баланс: {format_points(total)}.", ephemeral=True)


@bot.tree.command(name="выдать_выговор", description="Выдать выговор участнику")
@app_commands.guild_only()
@app_commands.describe(user="Участник")
async def issue_reprimand_command(interaction: Interaction, user: discord.Member):
    if not is_admin_user(interaction):
        await interaction.response.send_message("❌ У вас нет доступа.", ephemeral=True)
        return
    if user.bot:
        await interaction.response.send_message("❌ Нельзя выдать выговор боту.", ephemeral=True)
        return
    reprimands = add_reprimand(user.id, 1)
    save_data()
    await update_statistics_message()
    try:
        await user.send(f"⚠️ Вам выдан 1 выговор. Всего: {reprimands}/{MAX_REPRIMANDS}.")
    except discord.HTTPException:
        pass
    if reprimands >= MAX_REPRIMANDS:
        await remove_mafia_roles(user, "Получено 5 выговоров")
    await interaction.response.send_message(
        f"✅ Пользователю {user.mention} выдан 1 выговор. Всего: {reprimands}/{MAX_REPRIMANDS}.",
        ephemeral=True
    )


@bot.tree.command(name="снять_выговор", description="Снять выговор у участника")
@app_commands.guild_only()
@app_commands.describe(user="Участник", amount="Количество выговоров")
async def remove_reprimand_command(interaction: Interaction, user: discord.Member, amount: int = 1):
    if not is_admin_user(interaction):
        await interaction.response.send_message("❌ У вас нет доступа.", ephemeral=True); return
    if amount <= 0:
        await interaction.response.send_message("❌ Количество должно быть положительным.", ephemeral=True); return
    before = int(ensure_user_data(user.id).get("reprimands", 0)); after = remove_reprimand(user.id, amount)
    removed = before - after; save_data(); await update_statistics_message()
    try: await user.send(f"✅ Вам сняли {removed} выговор(ов). Осталось: {after}/{MAX_REPRIMANDS}.")
    except discord.HTTPException: pass
    await interaction.response.send_message(f"✅ У {user.mention} снято {removed} выговор(ов). Осталось: {after}/{MAX_REPRIMANDS}.", ephemeral=True)


# ============================================================
# СОБЫТИЕ READY
# ============================================================

@bot.event
async def on_ready():
    global data_loaded

    print("=" * 60)

    print(
        f"✅ Бот подключён: {bot.user}"
    )

    print(
        f"🆔 ID: {bot.user.id}"
    )

    print(
        f"🌐 Серверов: {len(bot.guilds)}"
    )

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
            name="Не забудь отправить отчет, Академка!"
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
