"""Подключение к Supabase.

Клиент создаётся один раз за сеанс благодаря @st.cache_resource.
Креды читаются из st.secrets (локально — .streamlit/secrets.toml,
на деплое — панель секретов Streamlit Community Cloud).
"""

from datetime import date, datetime, timedelta

import streamlit as st
from supabase import Client, create_client


def _monday(d: date) -> date:
    """Понедельник недели, в которую попадает дата d."""
    return d - timedelta(days=d.weekday())


@st.cache_resource
def get_client() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)


def get_day_log(client: Client, user_email: str, day: str) -> dict | None:
    """Строка day_logs за дату day и пользователя user_email (или None)."""
    result = (
        client.table("day_logs")
        .select("*")
        .eq("user_email", user_email)
        .eq("date", day)
        .execute()
    )
    return result.data[0] if result.data else None


def increment_day_log(client: Client, user_email: str, day: str, field: str) -> None:
    """Увеличить поле field на 1 за сегодня. Нет строки — создать с единицей."""
    row = get_day_log(client, user_email, day)
    if row:
        new_value = (row.get(field) or 0) + 1
        client.table("day_logs").update({field: new_value}).eq("id", row["id"]).execute()
    else:
        client.table("day_logs").insert(
            {"user_email": user_email, "date": day, field: 1}
        ).execute()


def set_day_log(
    client: Client, user_email: str, day: str, seen: int, approaches: int
) -> None:
    """Записать точные значения за день. Нет строки — создать."""
    row = get_day_log(client, user_email, day)
    values = {"seen": seen, "approaches": approaches}
    if row:
        client.table("day_logs").update(values).eq("id", row["id"]).execute()
    else:
        client.table("day_logs").insert(
            {"user_email": user_email, "date": day, **values}
        ).execute()


def get_contacts(client: Client) -> list[dict]:
    """Все карточки (база общая на двоих), новые сверху."""
    result = client.table("contacts").select("*").order("id", desc=True).execute()
    return result.data


def add_contact(
    client: Client, user_email: str, name: str, source: str, stage: str, notes: str
) -> None:
    """Добавить карточку контакта."""
    client.table("contacts").insert(
        {
            "user_email": user_email,
            "name": name,
            "source": source,
            "stage": stage,
            "notes": notes,
        }
    ).execute()


def update_contact(client: Client, contact_id: int, stage: str, notes: str) -> None:
    """Обновить стадию и заметки карточки по id."""
    client.table("contacts").update({"stage": stage, "notes": notes}).eq(
        "id", contact_id
    ).execute()


def set_contact_archived(client: Client, contact_id: int, archived: bool) -> None:
    """Положить карточку в архив (True) или вернуть из архива (False)."""
    client.table("contacts").update({"archived": archived}).eq(
        "id", contact_id
    ).execute()


def delete_contact(client: Client, contact_id: int) -> None:
    """Удалить карточку по id."""
    client.table("contacts").delete().eq("id", contact_id).execute()


def get_day_totals(client: Client, user_email: str | None = None) -> dict:
    """Суммы seen и approaches из day_logs.

    user_email=None — по всем, иначе только по этому человеку.
    """
    query = client.table("day_logs").select("seen, approaches")
    if user_email is not None:
        query = query.eq("user_email", user_email)
    rows = query.execute().data
    return {
        "seen": sum((r.get("seen") or 0) for r in rows),
        "approaches": sum((r.get("approaches") or 0) for r in rows),
    }


def get_weekly_day_logs(client: Client, user_email: str) -> dict[str, dict]:
    """seen/approaches человека, сгруппированные по неделям.

    Ключ — ISO-дата понедельника недели, значение — {"seen", "approaches"}.
    """
    rows = (
        client.table("day_logs")
        .select("date, seen, approaches")
        .eq("user_email", user_email)
        .execute()
        .data
    )
    weeks: dict[str, dict] = {}
    for r in rows:
        key = _monday(date.fromisoformat(r["date"])).isoformat()
        bucket = weeks.setdefault(key, {"seen": 0, "approaches": 0})
        bucket["seen"] += r.get("seen") or 0
        bucket["approaches"] += r.get("approaches") or 0
    return weeks


def get_weekly_contacts(client: Client, user_email: str) -> dict[str, int]:
    """Число новых карточек человека по неделям (по created_at).

    Ключ — ISO-дата понедельника недели, значение — количество карточек.
    """
    rows = (
        client.table("contacts")
        .select("created_at")
        .eq("user_email", user_email)
        .eq("archived", False)  # архивные в статистику не идут
        .execute()
        .data
    )
    weeks: dict[str, int] = {}
    for r in rows:
        created = r.get("created_at")
        if not created:
            continue
        d = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
        key = _monday(d).isoformat()
        weeks[key] = weeks.get(key, 0) + 1
    return weeks


def get_stage_counts(client: Client, user_email: str | None = None) -> dict:
    """Счётчики карточек по стадиям воронки.

    Возвращает накопительные числа этапов:
    - contact:  все карточки (любая стадия)
    - date:     стадии «свидание» или «закрытие»
    - closing:  стадия «закрытие»
    user_email=None — по всем, иначе только по этому человеку.
    """
    query = client.table("contacts").select("stage").eq("archived", False)
    if user_email is not None:
        query = query.eq("user_email", user_email)
    stages = [r["stage"] for r in query.execute().data]
    return {
        "contact": len(stages),
        "date": sum(1 for s in stages if s in ("свидание", "закрытие")),
        "closing": sum(1 for s in stages if s == "закрытие"),
    }


# --- Мини-CRM: таблица crm_contacts (отдельная от contacts) ---


def get_crm_contacts(client: Client) -> list[dict]:
    """Все CRM-контакты (база общая на двоих), новые сверху."""
    return client.table("crm_contacts").select("*").order("id", desc=True).execute().data


def add_crm_contact(client: Client, user_email: str, fields: dict) -> None:
    """Добавить CRM-контакт. fields — словарь колонок без user_email."""
    client.table("crm_contacts").insert({"user_email": user_email, **fields}).execute()


def update_crm_contact(client: Client, contact_id: int, fields: dict) -> None:
    """Обновить переданные поля CRM-контакта по id."""
    client.table("crm_contacts").update(fields).eq("id", contact_id).execute()


def delete_crm_contact(client: Client, contact_id: int) -> None:
    """Удалить CRM-контакт по id."""
    client.table("crm_contacts").delete().eq("id", contact_id).execute()
