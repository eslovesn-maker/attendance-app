import datetime
import uuid

import pandas as pd
import streamlit as st
from supabase import Client, create_client

st.set_page_config(page_title="통합 단체 출석부", page_icon="🌿", layout="wide")

PHOTO_BUCKET = "attendance-photos"


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


def apply_warm_theme() -> None:
    """따뜻하고 부드러운 크림/코랄 톤 스타일 적용"""
    st.markdown(
        """
        <style>
        /* 전체 배경 및 기본 글자 톤 */
        .stApp {
            background: linear-gradient(180deg, #FCF9F4 0%, #F7F1E7 100%);
            color: #3A322C;
        }

        /* 사이드바 따뜻한 샌드 톤 */
        section[data-testid="stSidebar"] {
            background-color: #F3ECE0;
            border-right: 1px solid #E6DACA;
        }

        /* 제목 및 서브헤더 여백/색감 */
        h1, h2, h3 {
            color: #3A2E26;
            letter-spacing: -0.01em;
        }

        /* 탭 디자인 부드럽게 */
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

        /* 폼 및 컨테이너 부드러운 카드 느낌 */
        div[data-testid="stForm"],
        div[data-testid="stExpander"] > details {
            background-color: #FFFDF9;
            border: 1px solid #EADFD0;
            border-radius: 16px;
            padding: 12px 16px;
            box-shadow: 0 4px 14px rgba(92, 70, 50, 0.04);
        }

        /* 기본 버튼 따뜻한 코랄/크림 스타일 */
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

        /* 폼 제출 버튼 강조 */
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

        /* 출석 기록일 빨간 칩 스타일 */
        div.stButton > button.red-date-btn {
            background-color: #FFE8E5;
            color: #B83227;
            border: 1px solid #F3B2AA;
            border-radius: 999px;
            padding: 2px 10px;
            font-size: 0.82rem;
            font-weight: 600;
            min-height: 1.9rem;
        }
        div.stButton > button.red-date-btn:hover {
            background-color: #FFD2CC;
            color: #8F1D14;
            border-color: #E58D82;
        }

        /* 데이터프레임 카드 테두리 */
        div[data-testid="stDataFrame"] {
            background-color: #FFFDF9;
            border: 1px solid #EADFD0;
            border-radius: 14px;
            padding: 6px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_warm_theme()


def normalize_mmdd(raw_val: str) -> str | None:
    """'03-15', '3/15', '3.15', '3월 15일' 등을 'MM-DD'로 정규화"""
    if not raw_val:
        return None
    cleaned = (
        raw_val.strip()
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
    """오늘 기준으로 다가오는 생일까지 남은 일수(오늘이면 0)"""
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
    """등록된 생일 명단, 모든 모임 명단, 출석 기록에 등장한 전체 인원 목록 수집"""
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
    """월별 출석 현황표(●/△/X)와 월별 출석률 추이 데이터프레임 반환"""
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
    """접속 시 오늘 생일 및 다가오는 생일 알림 배너/토스트 표시"""
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

# 1. 새 모임 만들기
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

    # 2. 모임 이름 변경 (출석 기록 및 사진 기록도 함께 새 이름으로 이전 후 기존 행 삭제)
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

    # 3. 모임 삭제 (영향 건수 안내 및 확인 단계 포함)
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

    # 4. 멤버 명단 수정 및 전체 인원 빠른 추가
    st.sidebar.subheader(f"🤝 [{selected_meeting}] 멤버 설정")
    current_members_str = meetings_map[selected_meeting]
    member_text_key = f"members_{selected_meeting}"
    if member_text_key not in st.session_state:
        st.session_state[member_text_key] = current_members_str

    names_input = st.sidebar.text_area(
        "참석자 명단 (쉼표로 구분)", key=member_text_key
    )
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
        if st.sidebar.button("🌼 선택 인원 명단에 넣기", key=f"btn_quick_add_{selected_meeting}") and selected_to_add:
            merged_list = current_parsed_members + selected_to_add
            updated_str = ", ".join(merged_list)
            st.session_state[member_text_key] = updated_str
            supabase.table("meetings").update(
                {
                    "members": updated_str,
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
            ).eq("meeting_name", selected_meeting).execute()
            st.sidebar.success(f"{len(selected_to_add)}명을 추가하고 저장했습니다!")
            st.rerun()

    if st.sidebar.button("💾 명단 저장하기", key=f"save_members_{selected_meeting}"):
        supabase.table("meetings").update(
            {
                "members": names_input,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        ).eq("meeting_name", selected_meeting).execute()
        st.sidebar.success("멤버 명단이 저장되었습니다!")
        st.rerun()

    member_list = current_parsed_members

    st.title(f"🌻 {selected_meeting} 통합 출석부")
    render_birthday_alerts(all_birthdays, alert_days=alert_window)

    tab1, tab2, tab3 = st.tabs(["📝 출석 체크 및 사진", "📈 연간 출석 현황 및 추이", "🎂 월별 생일"])

    with tab1:
        st.subheader(f"☀️ '{selected_meeting}' 모임 출석 입력")

        date_input_key = f"date_{selected_meeting}"
        if date_input_key not in st.session_state:
            st.session_state[date_input_key] = datetime.date.today()

        recorded_dates = (
            sorted(df["날짜"].astype(str).unique().tolist(), reverse=True)
            if not df.empty and "날짜" in df.columns
            else []
        )

        def _set_target_date(target_iso: str) -> None:
            try:
                st.session_state[date_input_key] = datetime.date.fromisoformat(target_iso)
            except ValueError:
                pass

        col1, col2 = st.columns(2)
        with col1:
            meeting_date = st.date_input("📅 모임 날짜 선택", key=date_input_key)

            if recorded_dates:
                st.markdown(
                    "<span style='font-size:0.84rem; color:#B83227; font-weight:600;'>"
                    "📌 출석 기록 있는 날짜 (클릭 시 이동):</span>",
                    unsafe_allow_html=True,
                )
                shown_dates = recorded_dates[:12]
                btn_cols = st.columns(4)
                for idx, d_str in enumerate(shown_dates):
                    with btn_cols[idx % 4]:
                        st.button(
                            f"● {d_str}",
                            key=f"red_btn_{selected_meeting}_{d_str}",
                            on_click=_set_target_date,
                            args=(d_str,),
                        )
                if len(recorded_dates) > 12:
                    st.caption(f"최근 12개 기록일 표시 (전체 {len(recorded_dates)}건)")
            else:
                st.caption("아직 출석 기록이 있는 날짜가 없습니다.")

        with col2:
            group_photos = st.file_uploader(
                "📸 모임 단체 사진 업로드 (최대 2장)",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                key=f"photo_{selected_meeting}_{meeting_date}",
            )

        date_str = str(meeting_date)
        saved_photos = load_photos(selected_meeting, date_str)

        if group_photos:
            st.write("📷 **새로 선택한 사진 미리보기 및 DB 저장**")
            selected_files = group_photos[:2]
            if len(group_photos) > 2:
                st.caption("최대 2장까지만 저장됩니다. 앞의 2장이 선택되었습니다.")
            preview_cols = st.columns(len(selected_files))
            for idx, photo in enumerate(selected_files):
                with preview_cols[idx]:
                    st.image(photo, caption=f"미리보기 {idx+1} ({date_str})", use_container_width=True)

            if st.button("📷 선택한 사진 저장하기", key=f"save_photo_{selected_meeting}_{date_str}"):
                for photo in selected_files:
                    upload_and_save_photo(photo, selected_meeting, date_str)
                st.success(f"{date_str} 모임 사진이 Storage 및 DB에 저장되었습니다!")
                st.rerun()

        st.markdown("---")
        st.write(f"🖼️ **저장된 모임 사진 ({date_str})**")
        if saved_photos:
            photo_cols = st.columns(2)
            for idx, p_row in enumerate(saved_photos):
                with photo_cols[idx % 2]:
                    st.image(
                        p_row["photo_url"],
                        caption=f"저장된 사진 {idx+1} ({p_row['record_date']})",
                        use_container_width=True,
                    )
                    if st.button("🗑️ 사진 삭제", key=f"del_photo_{p_row['id']}"):
                        delete_photo_record(p_row)
                        st.rerun()
        else:
            st.info(f"🌷 {date_str}에 저장된 사진이 아직 없습니다. 위에서 사진을 선택 후 '선택한 사진 저장하기'를 눌러주세요.")

        all_meeting_photos = load_photos(selected_meeting)
        if all_meeting_photos:
            with st.expander(f"🗂️ '{selected_meeting}' 날짜별 사진 갤러리 (총 {len(all_meeting_photos)}장)"):
                gallery_cols = st.columns(3)
                for idx, g_row in enumerate(all_meeting_photos):
                    with gallery_cols[idx % 3]:
                        st.image(
                            g_row["photo_url"],
                            caption=f"{g_row['record_date']} (#{idx+1})",
                            use_container_width=True,
                        )

        st.markdown("---")
        st.write("### 🌷 멤버별 출석 체크 (O: 출석, △: 지각/조퇴, X: 결석)")

        existing_day_df = df[df["날짜"].astype(str) == date_str] if not df.empty else pd.DataFrame()
        has_existing = not existing_day_df.empty
        existing_status_map = {}
        existing_note = ""
        if has_existing:
            st.caption(f"✏️ **{date_str}**에 이미 저장된 출석 기록이 있어 기존 값을 불러왔습니다. 수정 후 저장하면 덮어씌워집니다.")
            for _, r in existing_day_df.iterrows():
                existing_status_map[str(r["이름"])] = r["출석상태"]
            notes_non_empty = [str(n) for n in existing_day_df["비고"].dropna().tolist() if str(n).strip()]
            if notes_non_empty:
                existing_note = notes_non_empty[0]

        status_options = ["O", "△", "X"]
        with st.form(key=f"form_{selected_meeting}_{date_str}"):
            attendance_status = {}
            for member in member_list:
                default_status = existing_status_map.get(member, "O")
                default_idx = status_options.index(default_status) if default_status in status_options else 0
                attendance_status[member] = st.radio(
                    f"🍃 {member}",
                    status_options,
                    index=default_idx,
                    horizontal=True,
                    key=f"radio_{selected_meeting}_{date_str}_{member}",
                )

            note = st.text_input(
                "☕ 이번 모임 특이사항 (예: 뒷풀이 장소 등)",
                value=existing_note,
                key=f"note_{selected_meeting}_{date_str}",
            )
            submitted = st.form_submit_button("🌿 출석 기록 자동 저장")

            if submitted:
                supabase.table("attendance_records").delete().eq(
                    "meeting_name", selected_meeting
                ).eq("record_date", date_str).execute()

                if member_list:
                    payload = [
                        {
                            "meeting_name": selected_meeting,
                            "record_date": date_str,
                            "member_name": member,
                            "status": attendance_status[member],
                            "note": note,
                        }
                        for member in member_list
                    ]
                    supabase.table("attendance_records").insert(payload).execute()

                st.success(f"'{selected_meeting}'의 {date_str} 출석 기록이 DB에 자동 저장되었습니다!")
                st.rerun()

    with tab2:
        st.subheader(f"📈 '{selected_meeting}' 연간 출석 현황")
        if df.empty:
            st.info("🌱 아직 기록된 출석 데이터가 없습니다. '출석 체크 및 사진' 탭에서 데이터를 먼저 입력해 주세요.")
        else:
            parsed_all_dates = pd.to_datetime(df["날짜"], errors="coerce")
            available_years = sorted(
                parsed_all_dates.dt.year.dropna().astype(int).unique().tolist(),
                reverse=True,
            )
            year_options = ["전체 연도"] + [f"{y}년" for y in available_years]
            selected_year_label = st.selectbox(
                "🗓️ 조회 연도 필터",
                year_options,
                key=f"year_filter_{selected_meeting}",
            )

            if selected_year_label == "전체 연도":
                filtered_df = df.copy()
            else:
                target_year = int(selected_year_label.replace("년", ""))
                filtered_df = df[parsed_all_dates.dt.year == target_year].copy()
