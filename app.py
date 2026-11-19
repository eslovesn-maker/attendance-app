import datetime
import uuid

import pandas as pd
import streamlit as st
from supabase import Client, create_client

st.set_page_config(page_title="통합 단체 출석부", page_icon="🌿", layout="wide")

PHOTO_BUCKET = "attendance-photos"
WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


@st.cache_resource
def get_supabase_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


supabase = get_supabase_client()

if "confirm_delete" not in st.session_state:
    st.session_state.confirm_delete = False
if "birthday_toast_shown" not in st.session_state:
    st.session_state.birthday_toast_shown = False


def format_date_with_weekday(date_str: str) -> str:
    try:
        dt = datetime.date.fromisoformat(str(date_str).strip())
        return f"{dt.isoformat()}({WEEKDAY_KO[dt.weekday()]})"
    except ValueError:
        return str(date_str)


def apply_warm_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #FCF9F4 0%, #F7F1E7 100%);
            color: #3A322C;
        }
        section[data-testid="stSidebar"] {
            background-color: #F3ECE0;
            border-right: 1px solid #E6DACA;
        }
        h1, h2, h3 {
            color: #3A2E26;
            letter-spacing: -0.01em;
        }
        button[data-baseweb="tab"] {
            background-color: #F6EFE4;
            border-radius: 12px 12px 0 0;
            border: 1px solid #E8DEC9;
            margin-right: 6px;
            padding: 8px 16px;
            color: #5C4E44;
            font-weight: 600;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            background-color: #FFFDF9;
            color: #C85A32;
            border-bottom-color: #FFFDF9;
        }
        div[data-testid="stForm"],
        div[data-testid="stExpander"] > details {
            background-color: #FFFDF9;
            border: 1px solid #EADFD0;
            border-radius: 16px;
            padding: 12px 16px;
            box-shadow: 0 4px 14px rgba(92, 70, 50, 0.04);
        }
        div.stButton > button,
        div.stDownloadButton > button {
            background-color: #FFF7EE;
            color: #7A3E26;
            border: 1px solid #E5BEAA;
            border-radius: 12px;
            font-weight: 600;
            transition: all 0.18s ease;
        }
        div.stButton > button:hover,
        div.stDownloadButton > button:hover {
            background-color: #FDE8D7;
            border-color: #D49377;
            color: #5C2B18;
        }
        div[data-testid="stFormSubmitButton"] > button {
            background-color: #D96B43;
            color: #FFFFFF;
            border: none;
            border-radius: 12px;
            font-weight: 600;
            padding: 0.5rem 1.2rem;
        }
        div[data-testid="stFormSubmitButton"] > button:hover {
            background-color: #C25832;
            color: #FFFFFF;
        }
        div[data-testid="stDataFrame"] {
            background-color: #FFFDF9;
            border: 1px solid #EADFD0;
            border-radius: 14px;
            padding: 6px;
        }

        /* 기록일 버튼들을 컴팩트하게 나란히 배치 */
        div[data-testid="stHorizontalBlock"]:has(button[key^="red_btn_"]) {
            display: flex !important;
            flex-wrap: wrap !important;
            gap: 4px !important;
            align-items: center !important;
        }
        div[data-testid="stHorizontalBlock"]:has(button[key^="red_btn_"]) > div[data-testid="stColumn"] {
            width: auto !important;
            flex: 0 0 auto !important;
            min-width: unset !important;
            padding: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(button[key^="red_btn_"]) div.stButton > button {
            width: auto !important;
            padding: 3px 9px !important;
            min-height: 1.85rem !important;
            font-size: 0.82rem !important;
            border-radius: 999px !important;
            white-space: nowrap !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_warm_theme()


def normalize_mmdd(raw_val: str) -> str | None:
    if not raw_val:
        return None
    cleaned = (
        str(raw_val)
        .strip()
        .replace("년", "-")
        .replace("월", "-")
        .replace("일", "")
        .replace("/", "-")
        .replace(".", "-")
    )
    parts = [p.strip() for p in cleaned.split("-") if p.strip()]
    if len(parts) >= 2 and parts[-2].isdigit() and parts[-1].isdigit():
        m = int(parts[-2])
        d = int(parts[-1])
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{m:02d}-{d:02d}"
    return None


def days_until_birthday(mmdd: str, today: datetime.date) -> int | None:
    norm = normalize_mmdd(mmdd)
    if not norm:
        return None
    m, d = map(int, norm.split("-"))
    for year in (today.year, today.year + 1):
        try:
            target = datetime.date(year, m, d)
        except ValueError:
            target = datetime.date(year, 2, 28)
        if target >= today:
            return (target - today).days
    return None


def load_all_birthdays() -> list[dict]:
    try:
        res = (
            supabase.table("member_birthdays")
            .select("id, member_name, birthday, memo")
            .order("birthday")
            .order("member_name")
            .execute()
        )
    except Exception as e:
        st.warning(f"🌱 생일 목록을 불러오지 못했습니다: {e}")
        return []

    rows = []
    for row in res.data or []:
        norm = normalize_mmdd(row.get("birthday") or "")
        if norm:
            rows.append(
                {
                    "id": row["id"],
                    "member_name": row["member_name"],
                    "birthday": norm,
                    "memo": row.get("memo") or "",
                }
            )
    return rows


def upsert_birthday(member_name: str, mmdd: str, memo: str = "") -> None:
    supabase.table("member_birthdays").upsert(
        {
            "member_name": member_name.strip(),
            "birthday": mmdd,
            "memo": memo.strip(),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
        on_conflict="member_name",
    ).execute()


def delete_birthday(member_name: str) -> None:
    supabase.table("member_birthdays").delete().eq("member_name", member_name).execute()


def load_meetings() -> dict:
    try:
        res = supabase.table("meetings").select("meeting_name, members").order("meeting_name").execute()
    except Exception as e:
        st.error(f"🍂 모임 목록을 불러오지 못했습니다: {e}")
        return {}

    meetings_dict = {}
    for row in res.data or []:
        meetings_dict[row["meeting_name"]] = row["members"] or ""
    return meetings_dict


def collect_known_members(meetings_map: dict, all_birthdays: list[dict], df: pd.DataFrame) -> list[str]:
    names: list[str] = []
    for b in all_birthdays:
        n = (b.get("member_name") or "").strip()
        if n and n not in names:
            names.append(n)
    for m_str in meetings_map.values():
        for part in (m_str or "").split(","):
            n = part.strip()
            if n and n not in names:
                names.append(n)
    if not df.empty and "이름" in df.columns:
        for part in df["이름"].dropna().tolist():
            n = str(part).strip()
            if n and n not in names:
                names.append(n)
    return names


def load_attendance(meeting_name: str) -> pd.DataFrame:
    res = (
        supabase.table("attendance_records")
        .select("record_date, member_name, status, note")
        .eq("meeting_name", meeting_name)
        .order("record_date")
        .execute()
    )
    rows = res.data or []
    if not rows:
        return pd.DataFrame(columns=["날짜", "이름", "출석상태", "비고"])

    df = pd.DataFrame(rows).rename(
        columns={
            "record_date": "날짜",
            "member_name": "이름",
            "status": "출석상태",
            "note": "비고",
        }
    )
    return df[["날짜", "이름", "출석상태", "비고"]]


def load_photos(meeting_name: str, record_date: str | None = None) -> list:
    query = (
        supabase.table("attendance_photos")
        .select("id, photo_url, storage_path, record_date")
        .eq("meeting_name", meeting_name)
    )
    if record_date:
        query = query.eq("record_date", record_date).order("id")
    else:
        query = query.order("record_date", desc=True).order("id")
    res = query.execute()
    return res.data or []


def upload_and_save_photo(uploaded_file, meeting_name: str, record_date: str) -> None:
    ext = uploaded_file.name.split(".")[-1].lower() if "." in uploaded_file.name else "png"
    if ext not in ("png", "jpg", "jpeg", "webp"):
        ext = "png"

    content_type = uploaded_file.type or f"image/{ext}"
    safe_meeting = str(uuid.uuid4())[:8]
    storage_path = f"{safe_meeting}/{record_date}/{uuid.uuid4().hex}.{ext}"

    file_bytes = uploaded_file.getvalue()
    supabase.storage.from_(PHOTO_BUCKET).upload(
        path=storage_path,
        file=file_bytes,
        file_options={"content-type": content_type, "upsert": "false"},
    )

    public_url = supabase.storage.from_(PHOTO_BUCKET).get_public_url(storage_path)
    supabase.table("attendance_photos").insert(
        {
            "meeting_name": meeting_name,
            "record_date": record_date,
            "photo_url": public_url,
            "storage_path": storage_path,
        }
    ).execute()


def delete_photo_record(photo_row: dict) -> None:
    storage_path = photo_row.get("storage_path") or ""
    if storage_path:
        try:
            supabase.storage.from_(PHOTO_BUCKET).remove([storage_path])
        except Exception:
            pass
    supabase.table("attendance_photos").delete().eq("id", photo_row["id"]).execute()


def build_monthly_grid(stat_df: pd.DataFrame, member_list: list) -> tuple[pd.DataFrame, pd.DataFrame]:
    months = [f"{m}월" for m in range(1, 13)]
    parsed_dates = pd.to_datetime(stat_df["날짜"], errors="coerce")
    work_df = stat_df.copy()
    work_df["월"] = parsed_dates.dt.month

    priority = {"O": 3, "△": 2, "X": 1}
    symbol_map = {"O": "●", "△": "△", "X": "X"}

    all_names = list(dict.fromkeys(member_list + work_df["이름"].dropna().unique().tolist()))
    grid_rows = []
    month_present_counts = {m: 0 for m in range(1, 13)}
    month_recorded_counts = {m: 0 for m in range(1, 13)}

    for idx, name in enumerate(all_names, start=1):
        row_data = {"NO.": idx, "이름": name}
        person_df = work_df[work_df["이름"] == name]
        for m in range(1, 13):
            col_label = f"{m}월"
            m_sub = person_df[person_df["월"] == m]
            if m_sub.empty:
                row_data[col_label] = ""
            else:
                best_status = max(
                    m_sub["출석상태"].tolist(),
                    key=lambda s: priority.get(s, 0),
                )
                row_data[col_label] = symbol_map.get(best_status, best_status)
                month_recorded_counts[m] += 1
                if best_status == "O":
                    month_present_counts[m] += 1
        grid_rows.append(row_data)

    total_row = {"NO.": "", "이름": "계"}
    trend_rows = []
    for m in range(1, 13):
        col_label = f"{m}월"
        present_cnt = month_present_counts[m]
        recorded_cnt = month_recorded_counts[m]
        total_row[col_label] = present_cnt
        rate = round((present_cnt / recorded_cnt) * 100, 1) if recorded_cnt > 0 else 0.0
        trend_rows.append({"월": col_label, "출석률(%)": rate})

    grid_rows.append(total_row)
    grid_df = pd.DataFrame(grid_rows, columns=["NO.", "이름"] + months)
    trend_df = pd.DataFrame(trend_rows).set_index("월")
    return grid_df, trend_df


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def render_birthday_alerts(all_birthdays: list[dict], alert_days: int = 7) -> None:
    today = datetime.date.today()
    today_list = []
    upcoming_list = []

    for item in all_birthdays:
        diff = days_until_birthday(item["birthday"], today)
        if diff is None:
            continue
        m, d = map(int, item["birthday"].split("-"))
        label = f"{item['member_name']} ({m}월 {d}일)"
        if item["memo"]:
            label += f" - {item['memo']}"

        if diff == 0:
            today_list.append(label)
        elif 1 <= diff <= alert_days:
            upcoming_list.append((diff, label))

    upcoming_list.sort(key=lambda x: x[0])

    if not st.session_state.birthday_toast_shown:
        if today_list:
            st.toast(f"🎂 오늘 생일: {', '.join(today_list)}", icon="🎂")
        elif upcoming_list:
            soonest = upcoming_list[0]
            st.toast(f"🎈 {soonest[0]}일 뒤 생일: {soonest[1]}", icon="🎈")
        st.session_state.birthday_toast_shown = True

    if today_list:
        st.success(f"🎂 **오늘({today.month}월 {today.day}일) 생일 알림:** " + " | ".join(today_list))

    if upcoming_list:
        items_text = " | ".join(f"{lbl} (D-{diff})" for diff, lbl in upcoming_list)
        st.info(f"🎈 **다가오는 생일({alert_days}일 이내):** {items_text}")


st.sidebar.header("🌿 출석부 관리")

st.sidebar.subheader("✨ 새 모임 만들기")
new_meeting_name = st.sidebar.text_input("새 모임 이름 입력", placeholder="예: 31구역모임").strip()

meetings_map = load_meetings()
meeting_names = list(meetings_map.keys())
all_birthdays = load_all_birthdays()

if st.sidebar.button("🌱 모임 추가하기"):
    if not new_meeting_name:
        st.sidebar.warning("모임 이름을 입력해 주세요.")
    elif new_meeting_name in meetings_map:
        st.sidebar.warning("이미 존재하는 모임 이름입니다.")
    else:
        supabase.table("meetings").insert(
            {"meeting_name": new_meeting_name, "members": "참가자1, 참가자2"}
        ).execute()
        st.sidebar.success(f"'{new_meeting_name}' 모임이 생성되었습니다!")
        st.rerun()

st.sidebar.markdown("---")
alert_window = st.sidebar.slider("🎂 생일 미리 알림 기준(일)", min_value=1, max_value=30, value=7)
st.sidebar.markdown("---")

if meeting_names:
    selected_meeting = st.sidebar.selectbox("🏡 관리할 모임 선택", meeting_names)

    new_name = st.sidebar.text_input("선택한 모임 새 이름 변경", value=selected_meeting).strip()
    if st.sidebar.button("✏️ 이름 변경하기"):
        if not new_name:
            st.sidebar.warning("새 이름을 입력해 주세요.")
        elif new_name == selected_meeting:
            st.sidebar.info("변경할 이름이 현재 이름과 같습니다.")
        elif new_name in meetings_map:
            st.sidebar.warning("이미 존재하는 모임 이름입니다.")
        else:
            old_members = meetings_map[selected_meeting]
            old_records = (
                supabase.table("attendance_records")
                .select("record_date, member_name, status, note")
                .eq("meeting_name", selected_meeting)
                .execute()
                .data
                or []
            )
            old_photos = (
                supabase.table("attendance_photos")
                .select("record_date, photo_url, storage_path")
                .eq("meeting_name", selected_meeting)
                .execute()
                .data
                or []
            )
            supabase.table("meetings").insert(
                {"meeting_name": new_name, "members": old_members}
            ).execute()
            if old_records:
                migrated = [
                    {
                        "meeting_name": new_name,
                        "record_date": r["record_date"],
                        "member_name": r["member_name"],
                        "status": r["status"],
                        "note": r["note"],
                    }
                    for r in old_records
                ]
                supabase.table("attendance_records").upsert(
                    migrated, on_conflict="meeting_name,record_date,member_name"
                ).execute()
            if old_photos:
                migrated_photos = [
                    {
                        "meeting_name": new_name,
                        "record_date": p["record_date"],
                        "photo_url": p["photo_url"],
                        "storage_path": p.get("storage_path") or "",
                    }
                    for p in old_photos
                ]
                supabase.table("attendance_photos").insert(migrated_photos).execute()
                supabase.table("attendance_photos").delete().eq("meeting_name", selected_meeting).execute()

            supabase.table("meetings").delete().eq("meeting_name", selected_meeting).execute()
            st.rerun()

    if not st.session_state.confirm_delete:
        if st.sidebar.button("🧺 현재 모임 삭제하기"):
            st.session_state.confirm_delete = True
            st.rerun()
    else:
        target_records = (
            supabase.table("attendance_records")
            .select("id")
            .eq("meeting_name", selected_meeting)
            .execute()
            .data
            or []
        )
        target_photos = (
            supabase.table("attendance_photos")
            .select("id, storage_path")
            .eq("meeting_name", selected_meeting)
            .execute()
            .data
            or []
        )
        st.sidebar.error(
            f"☕ '{selected_meeting}'을(를) 삭제하면 출석 기록 **{len(target_records)}건**과 "
            f"사진 **{len(target_photos)}장**이 함께 삭제됩니다. 계속할까요?"
        )
        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.sidebar.button("✅ 예, 삭제"):
                for p in target_photos:
                    delete_photo_record(p)
                supabase.table("meetings").delete().eq("meeting_name", selected_meeting).execute()
                st.session_state.confirm_delete = False
                st.rerun()
        with col2:
            if st.sidebar.button("🕊️ 아니오"):
                st.session_state.confirm_delete = False
                st.rerun()

    st.sidebar.markdown("---")

    st.sidebar.subheader(f"🤝 [{selected_meeting}] 멤버 설정")
    current_members_str = meetings_map[selected_meeting]
    member_text_key = f"members_{selected_meeting}"
    if member_text_key not in st.session_state:
        st.session_state[member_text_key] = current_members_str

    names_input = st.sidebar.text_area("참석자 명단 (쉼표로 구분)", key=member_text_key)
    current_parsed_members = [name.strip() for name in names_input.split(",") if name.strip()]

    df = load_attendance(selected_meeting)
    known_members = collect_known_members(meetings_map, all_birthdays, df)
    addable_members = [m for m in known_members if m not in current_parsed_members]

    if addable_members:
        selected_to_add = st.sidebar.multiselect(
            "기존 등록 인원에서 빠른 추가",
            options=addable_members,
            key=f"quick_add_{selected_meeting}",
        )
        if st.sidebar.button("🌼 선택 인원 명단에 넣기", key=f"btn_quick_
