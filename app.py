"""Трекер прогресса — интерфейс на Streamlit с Supabase.

Вкладки: «Подходы», «Карточки», «Статистика», «База данных» (мини-CRM).
"""

from datetime import date

import pandas as pd
import streamlit as st

from db import (
    add_contact,
    add_crm_contact,
    delete_contact,
    delete_crm_contact,
    get_client,
    get_contacts,
    get_crm_contacts,
    get_day_log,
    get_day_totals,
    get_stage_counts,
    get_weekly_contacts,
    get_weekly_day_logs,
    set_day_log,
    update_contact,
    update_crm_contact,
)

st.set_page_config(page_title="Трекер прогресса", page_icon="📈")


def require_password() -> None:
    """Общий пароль на входе. Без входа рисуем только форму и st.stop()."""
    if st.session_state.get("authed"):
        return
    st.title("🔒 Вход")
    password = st.text_input("Пароль", type="password")
    if st.button("Войти"):
        if password == st.secrets["app_password"]:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Неверный пароль")
    st.stop()


require_password()

SOURCES = ["улица", "соцсети", "сайт"]
STAGES = ["контакт", "свидание", "закрытие"]
RELATIONSHIPS = ["дружеские", "романтические", "знакомые", "другое"]

st.title("📈 Трекер прогресса")

# Один селектор на всё приложение: кто вносит запись (= user_email).
# На главной странице (а не в сайдбаре), чтобы был виден на телефоне без меню.
user_email = st.selectbox("Кто вносит запись", ["Danylo", "Pavlo"])

client = get_client()

tab_today, tab_cards, tab_stats, tab_crm = st.tabs(
    ["Подходы", "Карточки", "Статистика", "База данных"]
)

with tab_today:
    # Дата записи: по умолчанию сегодня, будущие даты запрещены.
    selected_date = st.date_input("Дата", value=date.today(), max_value=date.today())
    selected_day = selected_date.isoformat()

    # Числа этого человека за выбранную дату.
    row = get_day_log(client, user_email, selected_day)
    seen = (row or {}).get("seen") or 0
    approaches = (row or {}).get("approaches") or 0
    missed = seen - approaches

    # Ключи привязаны к человеку и дате: при смене дня/человека поля
    # пересоздаются и подхватывают значения этого дня из БД.
    seen_key = f"seen_{user_email}_{selected_day}"
    appr_key = f"appr_{user_email}_{selected_day}"

    def save_day(day: str, sk: str, ak: str) -> None:
        """on_change: пишем оба значения в БД (срабатывает только при изменении)."""
        set_day_log(client, user_email, day, st.session_state[sk], st.session_state[ak])

    c1, c2, c3 = st.columns(3)
    c1.number_input(
        "Увидел", min_value=0, step=1, value=seen, key=seen_key,
        on_change=save_day, args=(selected_day, seen_key, appr_key),
    )
    c2.number_input(
        "Подошёл", min_value=0, step=1, value=approaches, key=appr_key,
        on_change=save_day, args=(selected_day, seen_key, appr_key),
    )
    c3.metric("Упущено", missed)

    # Сброс дня — с подтверждением, как у удаления карточки.
    st.divider()
    if st.session_state.get("confirm_reset"):
        st.warning("Точно обнулить день?")
        yes, cancel = st.columns(2)
        if yes.button("Да", key="reset_yes", use_container_width=True):
            set_day_log(client, user_email, selected_day, 0, 0)
            st.session_state.pop("confirm_reset", None)
            st.rerun()
        if cancel.button("Отмена", key="reset_cancel", use_container_width=True):
            st.session_state.pop("confirm_reset", None)
            st.rerun()
    else:
        if st.button("Сбросить день", key="reset_day"):
            st.session_state["confirm_reset"] = True
            st.rerun()

with tab_cards:
    st.header("Карточки")

    # --- Форма добавления: пишем в БД только по submit ---
    with st.form("add_contact", clear_on_submit=True):
        name = st.text_input("Имя")
        source = st.selectbox("Источник", SOURCES)
        stage = st.selectbox("Стадия", STAGES, index=0)
        notes = st.text_area("Заметки")
        submitted = st.form_submit_button("Добавить карточку")
    if submitted:
        if name.strip():
            add_contact(client, user_email, name.strip(), source, stage, notes)
            st.success(f"Карточка «{name.strip()}» добавлена")
            st.rerun()
        else:
            st.warning("Имя не может быть пустым")

    st.divider()

    # --- Список карточек, сгруппированный по людям (база общая на двоих) ---
    # get_contacts отдаёт новые сверху, поэтому внутри группы порядок уже верный.
    contacts = get_contacts(client)
    if not contacts:
        st.caption("Пока нет ни одной карточки.")
    for person in ["Danylo", "Pavlo"]:
        person_contacts = [c for c in contacts if c["user_email"] == person]
        if not person_contacts:
            continue
        st.subheader(person)
        for contact in person_contacts:
            title = f"{contact['name']} — {contact['stage']} ({contact['source']})"
            with st.expander(title):
                new_stage = st.selectbox(
                    "Стадия",
                    STAGES,
                    index=STAGES.index(contact["stage"]),
                    key=f"stage_{contact['id']}",
                )
                if st.button("Сохранить", key=f"save_{contact['id']}"):
                    # Сохраняем только стадию, журнал заметок не трогаем.
                    update_contact(
                        client, contact["id"], new_stage, contact.get("notes") or ""
                    )
                    st.success("Сохранено")
                    st.rerun()

                # Журнал заметок: старые записи показываем как есть, не редактируем.
                journal = contact.get("notes") or ""
                if journal.strip():
                    st.text(journal)
                else:
                    st.caption("Записей пока нет.")

                entry = st.text_area("Новая запись", key=f"newnote_{contact['id']}")
                if st.button("Добавить", key=f"addnote_{contact['id']}"):
                    if entry.strip():
                        line = f"— {date.today().isoformat()}: {entry.strip()}"
                        # Дописываем в начало, старые записи сохраняем.
                        updated = line + ("\n" + journal if journal else "")
                        update_contact(client, contact["id"], contact["stage"], updated)
                        st.rerun()
                    else:
                        st.warning("Запись не может быть пустой")

                # Удаление в два шага: первая кнопка только открывает
                # подтверждение (запоминаем id в session_state), удаляет — «Да».
                if st.session_state.get("confirm_delete") == contact["id"]:
                    st.warning("Точно удалить?")
                    yes, cancel = st.columns(2)
                    if yes.button("Да", key=f"yes_{contact['id']}", use_container_width=True):
                        delete_contact(client, contact["id"])
                        st.session_state.pop("confirm_delete", None)
                        st.rerun()
                    if cancel.button("Отмена", key=f"cancel_{contact['id']}", use_container_width=True):
                        st.session_state.pop("confirm_delete", None)
                        st.rerun()
                else:
                    if st.button("Удалить", key=f"del_{contact['id']}"):
                        st.session_state["confirm_delete"] = contact["id"]
                        st.rerun()

with tab_stats:
    st.header("Статистика")

    def pct(part: int, whole: int) -> str:
        """Конверсия part от whole в процентах (защита от деления на 0)."""
        return f"{round(part / whole * 100)}%" if whole else "—"

    # === 1. Моя динамика (человек из сайдбара) ===
    st.subheader(f"Моя динамика — {user_email}")

    wd = get_weekly_day_logs(client, user_email)
    wc = get_weekly_contacts(client, user_email)

    # Недели, по которым есть хоть какие-то данные (day_logs или contacts).
    weeks = sorted(set(wd) | set(wc))
    if not weeks:
        st.caption("Пока нет данных для динамики.")
    else:
        def week_metrics(w: str) -> dict:
            """Числа за неделю w: подходы, контакты, конверсия подхода (%)."""
            seen = wd.get(w, {}).get("seen", 0)
            appr = wd.get(w, {}).get("approaches", 0)
            return {
                "approaches": appr,
                "contacts": wc.get(w, 0),
                "conv": round(appr / seen * 100) if seen else 0,
            }

        # По умолчанию: A = предпоследняя неделя, B = последняя.
        default_b = len(weeks) - 1
        default_a = max(default_b - 1, 0)

        wa, wb = st.columns(2)
        week_a = wa.selectbox("Неделя A", weeks, index=default_a, key="week_a")
        week_b = wb.selectbox("Неделя B", weeks, index=default_b, key="week_b")

        a, b = week_metrics(week_a), week_metrics(week_b)

        st.caption("Неделя B в сравнении с неделей A")
        d1, d2, d3 = st.columns(3)
        d1.metric("Подходы", b["approaches"], delta=b["approaches"] - a["approaches"])
        # Дельта — числовая (в п.п.), чтобы рост красился зелёным.
        # delta_color="normal" (по умолчанию): >0 зелёный ↑, <0 красный ↓.
        d2.metric(
            "Конверсия подхода",
            f"{b['conv']}%",
            delta=b["conv"] - a["conv"],
            delta_color="normal",
            help="Подошёл / увидел. Дельта — изменение в процентных пунктах.",
        )
        d3.metric("Контакты", b["contacts"], delta=b["contacts"] - a["contacts"])

        # Тренд подходов по неделям с выбором периода.
        period = st.radio(
            "Период тренда",
            ["Последние 4", "Последние 8", "Все"],
            index=0,
            horizontal=True,
        )
        limit = {"Последние 4": 4, "Последние 8": 8}.get(period)
        shown = weeks[-limit:] if limit else weeks
        trend = pd.DataFrame(
            {"Подходы": [wd.get(w, {}).get("approaches", 0) for w in shown]},
            index=shown,
        )
        st.line_chart(trend)

    # === 2. Воронка (всё время, акцент на пройденном пути) ===
    st.divider()
    st.subheader("Воронка")

    totals = get_day_totals(client, user_email)
    stages = get_stage_counts(client, user_email)
    steps = [
        ("Подошёл", totals["approaches"]),
        ("Контакт", stages["contact"]),
        ("Свидание", stages["date"]),
        ("Закрытие", stages["closing"]),
    ]
    cols = st.columns(len(steps))
    for i, (col, (name, value)) in enumerate(zip(cols, steps)):
        col.metric(name, value)
        if i > 0:
            prev_name, prev_value = steps[i - 1]
            col.caption(f"↳ {pct(value, prev_value)} от «{prev_name}»")

    # === 3. Упущено — неприметной подписью ===
    missed = totals["seen"] - totals["approaches"]
    st.caption(f"упущено (увидел − подошёл): {missed}")

    # === 4. Сравнение с другом — компактно, в самом низу ===
    st.divider()
    st.subheader("Сравнение с другом")
    cmp_cols = st.columns(2)
    for col, person in zip(cmp_cols, ["Danylo", "Pavlo"]):
        t = get_day_totals(client, person)
        s = get_stage_counts(client, person)
        with col:
            st.markdown(f"**{person}**")
            st.write(f"Подходы: {t['approaches']}")
            st.write(f"Контакты: {s['contact']}")
            st.write(f"Закрытия: {s['closing']}")

with tab_crm:
    st.header("База данных")

    # --- Форма добавления: пишем в БД только по submit ---
    with st.form("add_crm", clear_on_submit=True):
        crm_name = st.text_input("Имя")
        f1, f2 = st.columns(2)
        crm_instagram = f1.text_input("Инстаграм")
        crm_phone = f2.text_input("Телефон")
        crm_rel = st.selectbox("Тип отношений", RELATIONSHIPS)
        crm_tags = st.text_input("Теги / интересы")
        crm_city = st.text_input("Город / район")
        crm_last = st.date_input("Дата последнего контакта", value=date.today())
        crm_notes = st.text_area("Заметки")
        crm_submitted = st.form_submit_button("Добавить в базу")
    if crm_submitted:
        if crm_name.strip():
            add_crm_contact(
                client,
                user_email,
                {
                    "name": crm_name.strip(),
                    "instagram": crm_instagram.strip(),
                    "phone": crm_phone.strip(),
                    "relationship": crm_rel,
                    "tags": crm_tags.strip(),
                    "city": crm_city.strip(),
                    "last_contact": crm_last.isoformat(),
                    "notes": crm_notes,
                },
            )
            st.success(f"«{crm_name.strip()}» добавлен(а) в базу")
            st.rerun()
        else:
            st.warning("Имя не может быть пустым")

    st.divider()

    crm_contacts = get_crm_contacts(client)

    # --- Поиск и фильтры ---
    s1, s2, s3 = st.columns(3)
    query = s1.text_input("Поиск (имя / теги)").strip().lower()
    rel_filter = s2.selectbox("Тип отношений", ["все"] + RELATIONSHIPS)
    cities = sorted({c.get("city") for c in crm_contacts if c.get("city")})
    city_filter = s3.selectbox("Город", ["все"] + cities)

    def matches(c: dict) -> bool:
        if query and query not in (
            f"{c.get('name') or ''} {c.get('tags') or ''}".lower()
        ):
            return False
        if rel_filter != "все" and c.get("relationship") != rel_filter:
            return False
        if city_filter != "все" and c.get("city") != city_filter:
            return False
        return True

    filtered = [c for c in crm_contacts if matches(c)]
    if not filtered:
        st.caption("Ничего не найдено.")

    # --- Таблицы-редакторы, сгруппированные по человеку ---
    # Колонки таблицы (порядок = порядок в data_editor).
    CRM_COLS = [
        "name", "relationship", "tags", "city",
        "instagram", "phone", "last_contact", "notes",
    ]
    CRM_CONFIG = {
        "name": st.column_config.TextColumn("Имя"),
        "relationship": st.column_config.SelectboxColumn(
            "Тип отношений", options=RELATIONSHIPS
        ),
        "tags": st.column_config.TextColumn("Теги / интересы"),
        "city": st.column_config.TextColumn("Город / район"),
        "instagram": st.column_config.TextColumn("Инстаграм"),
        "phone": st.column_config.TextColumn("Телефон"),
        "last_contact": st.column_config.DateColumn("Последний контакт"),
        "notes": st.column_config.TextColumn("Заметки"),
    }

    def text_cell(v) -> str:
        """Ячейку текста приводим к чистой строке ('' для пустых)."""
        return "" if v is None or pd.isna(v) else str(v).strip()

    def date_cell(v) -> str | None:
        """Ячейку даты — в ISO-строку или None."""
        if v is None or pd.isna(v):
            return None
        return (v.date() if hasattr(v, "date") else v).isoformat()

    def row_fields(r) -> dict:
        """Строка таблицы -> словарь полей для БД."""
        return {
            "name": text_cell(r["name"]),
            "relationship": text_cell(r["relationship"]) or RELATIONSHIPS[0],
            "tags": text_cell(r["tags"]),
            "city": text_cell(r["city"]),
            "instagram": text_cell(r["instagram"]),
            "phone": text_cell(r["phone"]),
            "last_contact": date_cell(r["last_contact"]),
            "notes": text_cell(r["notes"]),
        }

    for person in ["Danylo", "Pavlo"]:
        person_contacts = [c for c in filtered if c["user_email"] == person]
        if not person_contacts:
            continue
        st.subheader(person)

        # id уходит в индекс (скрыт), чтобы знать, какую строку обновлять/удалять.
        df = pd.DataFrame(
            [
                {
                    "id": c["id"],
                    "name": c.get("name") or "",
                    "relationship": c.get("relationship") or RELATIONSHIPS[0],
                    "tags": c.get("tags") or "",
                    "city": c.get("city") or "",
                    "instagram": c.get("instagram") or "",
                    "phone": c.get("phone") or "",
                    "last_contact": (
                        date.fromisoformat(c["last_contact"])
                        if c.get("last_contact")
                        else None
                    ),
                    "notes": c.get("notes") or "",
                }
                for c in person_contacts
            ],
            columns=["id"] + CRM_COLS,
        ).set_index("id")

        edited = st.data_editor(
            df,
            num_rows="dynamic",
            hide_index=True,
            column_config=CRM_CONFIG,
            key=f"crm_editor_{person}",
        )

        if st.button("Сохранить изменения", key=f"crm_save_{person}"):
            original = {c["id"]: c for c in person_contacts}
            kept_ids = set()
            for idx, r in edited.iterrows():
                if pd.isna(idx):
                    # Новая строка, добавленная прямо в таблице.
                    fields = row_fields(r)
                    if fields["name"]:
                        add_crm_contact(client, person, fields)
                    continue
                cid = int(idx)
                kept_ids.add(cid)
                fields = row_fields(r)
                # Обновляем только реально изменившиеся строки.
                orig = original[cid]
                if any(fields[k] != (orig.get(k) or ("" if k != "last_contact" else None))
                       for k in fields):
                    update_crm_contact(client, cid, fields)
            # Удалённые строки — те, чьих id больше нет в таблице.
            for cid in set(original) - kept_ids:
                delete_crm_contact(client, cid)
            st.success("Изменения сохранены")
            st.rerun()
