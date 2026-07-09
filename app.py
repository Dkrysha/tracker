"""Трекер прогресса — интерфейс на Streamlit с Supabase.

Вкладки: «Подходы», «Карточки», «Статистика», «Соревнование».
"""

# redeploy: 2026-06-11 — форс-передеплой Streamlit Cloud (синхронизация app.py/db.py)

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from db import (
    add_contact,
    delete_contact,
    get_client,
    get_competition_score,
    get_contacts,
    get_day_log,
    get_day_totals,
    get_stage_counts,
    get_weekly_contacts,
    get_weekly_day_logs,
    increment_day_log,
    set_contact_archived,
    set_day_log,
    update_contact,
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

st.title("📈 Трекер прогресса")

# Один селектор на всё приложение: кто вносит запись (= user_email).
# На главной странице (а не в сайдбаре), чтобы был виден на телефоне без меню.
user_email = st.selectbox("Кто вносит запись", ["Danylo", "Pavlo"])

client = get_client()

tab_today, tab_cards, tab_stats, tab_contest = st.tabs(
    ["Подходы", "Карточки", "Статистика", "Соревнование"]
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

    # Смелость: отдельная кнопка для подходов, что дались тяжело.
    # Пишем в БД только по нажатию (increment_day_log трогает поле brave).
    brave = (row or {}).get("brave") or 0
    b1, b2 = st.columns([1, 2])
    b1.metric("Смелость", brave)
    if b2.button("💪 +1 смелость", key=f"brave_{user_email}_{selected_day}"):
        increment_day_log(client, user_email, selected_day, "brave")
        st.rerun()

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

    def render_card(contact: dict) -> None:
        """Тело карточки внутри expander: стадия, журнал, архив, удаление."""
        archived = bool(contact.get("archived"))
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

        # Архив: одна кнопка переключает archived в обе стороны.
        if archived:
            if st.button("Вернуть из архива", key=f"unarch_{contact['id']}"):
                set_contact_archived(client, contact["id"], False)
                st.rerun()
        else:
            if st.button("В архив", key=f"arch_{contact['id']}"):
                set_contact_archived(client, contact["id"], True)
                st.rerun()

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

    # --- Список карточек, сгруппированный по людям (база общая на двоих) ---
    # get_contacts отдаёт новые сверху, поэтому внутри группы порядок уже верный.
    contacts = get_contacts(client)
    active = [c for c in contacts if not c.get("archived")]
    archived = [c for c in contacts if c.get("archived")]

    if not active:
        st.caption("Пока нет ни одной карточки.")
    for person in ["Danylo", "Pavlo"]:
        person_contacts = [c for c in active if c["user_email"] == person]
        if not person_contacts:
            continue
        st.subheader(person)
        for contact in person_contacts:
            title = f"{contact['name']} — {contact['stage']} ({contact['source']})"
            with st.expander(title):
                render_card(contact)

    # --- Архив: свёрнутый раздел со всеми архивными карточками ---
    if archived:
        st.divider()
        with st.expander(f"Архив ({len(archived)})"):
            for contact in archived:
                title = f"{contact['name']} — {contact['stage']} ({contact['source']})"
                with st.expander(title):
                    render_card(contact)

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

    # Числа обоих людей (архивные карточки уже исключены в get_stage_counts).
    people = {}
    for person in ["Danylo", "Pavlo"]:
        t = get_day_totals(client, person)
        s = get_stage_counts(client, person)
        people[person] = {
            "approaches": t["approaches"],
            "missed": t["seen"] - t["approaches"],
            "contacts": s["contact"],
            "closing": s["closing"],
        }

    cmp_cols = st.columns(2)
    for col, person in zip(cmp_cols, ["Danylo", "Pavlo"]):
        p = people[person]
        with col:
            st.markdown(f"**{person}**")
            st.write(f"Подошёл: {p['approaches']}")
            st.write(f"Упущено: {p['missed']}")
            st.write(f"Контакты: {p['contacts']}")
            st.write(f"Закрытия: {p['closing']}")

    # Сводка с точки зрения выбранного в сайдбаре человека («ты») против друга.
    friend = "Pavlo" if user_email == "Danylo" else "Danylo"
    me, other = people[user_email], people[friend]

    def vs(field: str) -> str:
        """Разница «ты − друг» со знаком (+/−) для наглядности."""
        diff = me[field] - other[field]
        return f"ты +{diff}" if diff > 0 else (f"ты {diff}" if diff < 0 else "поровну")

    st.caption(f"Ты ({user_email}) vs друг ({friend})")
    st.write(f"Подходы: {vs('approaches')}  ·  Закрытия: {vs('closing')}")

with tab_contest:
    st.header("Соревнование")
    st.caption(
        "Danylo против Pavlo. Баллы: подход 1 (не более 10 за день), "
        "контакт 2, свидание 5, закрытие 8, смелость 1. Считаются автоматически."
    )

    # Период по умолчанию — текущая неделя (пн–вс).
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    p1, p2 = st.columns(2)
    contest_from = p1.date_input("С", value=week_start, key="contest_from")
    contest_to = p2.date_input("По", value=week_end, key="contest_to")

    if contest_from > contest_to:
        st.warning("Дата «с» позже даты «по».")
    else:
        scores = {
            person: get_competition_score(
                client, person, contest_from.isoformat(), contest_to.isoformat()
            )
            for person in ["Danylo", "Pavlo"]
        }

        # Крупно: очки обоих рядом.
        s1, s2 = st.columns(2)
        s1.metric("Danylo", scores["Danylo"]["total"])
        s2.metric("Pavlo", scores["Pavlo"]["total"])

        diff = scores["Danylo"]["total"] - scores["Pavlo"]["total"]
        if diff > 0:
            st.success(f"🏆 Ведёт Danylo — на {diff} б.")
        elif diff < 0:
            st.success(f"🏆 Ведёт Pavlo — на {-diff} б.")
        else:
            st.info("Ничья.")

        # Разбивка под каждым: откуда набраны баллы.
        st.divider()
        labels = [
            ("approach", "Подходы"),
            ("contact", "Контакты"),
            ("date", "Свидания"),
            ("closing", "Закрытия"),
            ("brave", "Смелость"),
        ]
        b1, b2 = st.columns(2)
        for col, person in zip((b1, b2), ["Danylo", "Pavlo"]):
            with col:
                st.markdown(f"**{person}**")
                for key, label in labels:
                    st.write(f"{label}: {scores[person][key]}")
