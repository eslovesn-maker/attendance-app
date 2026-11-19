import datetime
import uuid

import pandas as pd
import streamlit as st
from supabase import Client, create_client

st.set_page_config(page_title="통합 단체 출석부", layout="wide")

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
        st.warning(f"생일 목록을 불러오지 못했습니다: {e}")
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
        st.error(f"모임 목록을 불러오지 못했습니다: {e}")
        return {}

    meetings_dict = {}
    for row in res.data or []:
        meetings_dict[row["meeting_name"]] = row["members"]
    return meetings_dict


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


def load_photos(meeting_name: str, record_date: str) -> list:
    res = (
        supabase.table("attendance_photos")
        .select("id, photo_url, storage_path, record_date")
        .eq("meeting_name", meeting_name)
        .eq("record_date", record_date)
        .order("id")
        .execute()
    )
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


def build_monthly_grid(stat_df: pd.DataFrame, member_list: list) -> pd.DataFrame:
    months = [f"{m}월" for m in range(1, 13)]
    parsed_dates = pd.to_datetime(stat_df["날짜"], errors="coerce")
    work_df = stat_df.copy()
    work_df["월"] = parsed_dates.dt.month

    priority = {"O": 3, "△": 2, "X": 1}
    symbol_map = {"O": "●", "△": "△", "X": "X"}

    all_names = list(dict.fromkeys(member_list + work_df["이름"].dropna().unique().tolist()))
    grid_rows = []
    month_counts = {m: 0 for m in range(1, 13)}

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
                if best_status == "O":
                    month_counts[m] += 1
        grid_rows.append(row_data)

    total_row = {"NO.": "", "이름": "계"}
    for m in range(1, 13):
        total_row[f"{m}월"] = month_counts[m] if month_counts[m] > 0 else 0
    grid_rows.append(total_row)

    return pd.DataFrame(grid_rows, columns=["NO.", "이름"] + months)


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


st.sidebar.header("⚙️ 출석부 관리")

# 1. 새 모임 만들기 (자동 저장)
st.sidebar.subheader("➕ 새 모임 만들기")
new_meeting_name = st.sidebar.text_input("새 모임 이름 입력", placeholder="예: 31구역모임").strip()

meetings_map = load_meetings()
meeting_names = list(meetings_map.keys())
all_birthdays = load_all_birthdays()

if st.sidebar.button("모임 추가하기"):
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
    selected_meeting = st.sidebar.selectbox("📂 관리할 모임 선택", meeting_names)

    # 2. 모임 이름 변경 (출석 기록 및 사진 기록도 함께 새 이름으로 이전 후 기존 행 삭제)
    new_name = st.sidebar.text_input("선택한 모임 새 이름 변경", value=selected_meeting).strip()
    if st.sidebar.button("이름 변경하기"):
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

    # 3. 모임 삭제 (확인 단계 포함)
    if not st.session_state.confirm_delete:
        if st.sidebar.button("현재 모임 삭제하기"):
            st.session_state.confirm_delete = True
            st.rerun()
    else:
        st.sidebar.error(f"⚠️ '{selected_meeting}'을(를) 정말 삭제하시겠습니까?")
        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.sidebar.button("예, 삭제"):
                photo_rows = (
                    supabase.table("attendance_photos")
                    .select("id, storage_path")
                    .eq("meeting_name", selected_meeting)
                    .execute()
                    .data
                    or []
                )
                for p in photo_rows:
                    delete_photo_record(p)
                supabase.table("meetings").delete().eq("meeting_name", selected_meeting).execute()
                st.session_state.confirm_delete = False
                st.rerun()
        with col2:
            if st.sidebar.button("아니오"):
                st.session_state.confirm_delete = False
                st.rerun()

    st.sidebar.markdown("---")

    # 4. 멤버 명단 수정 및 자동 저장
    st.sidebar.subheader(f"👥 [{selected_meeting}] 멤버 설정")
    current_members_str = meetings_map[selected_meeting]
    names_input = st.sidebar.text_area(
        "참석자 명단 (쉼표로 구분)", value=current_members_str, key=f"members_{selected_meeting}"
    )
    if st.sidebar.button("명단 저장하기", key=f"save_members_{selected_meeting}"):
        supabase.table("meetings").update(
            {
                "members": names_input,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        ).eq("meeting_name", selected_meeting).execute()
        st.sidebar.success("멤버 명단이 저장되었습니다!")
        st.rerun()

    member_list = [name.strip() for name in names_input.split(",") if name.strip()]
    df = load_attendance(selected_meeting)

    st.title(f"📊 {selected_meeting} 통합 출석부")
    render_birthday_alerts(all_birthdays, alert_days=alert_window)

    tab1, tab2, tab3 = st.tabs(["📝 출석 체크 및 사진", "📈 연간 출석 현황 및 추이", "🎂 월별 생일"])

    with tab1:
        st.subheader(f"'{selected_meeting}' 모임 출석 입력")

        col1, col2 = st.columns(2)
        with col1:
            meeting_date = st.date_input(
                "모임 날짜 선택", datetime.date.today(), key=f"date_{selected_meeting}"
            )
        with col2:
            group_photos = st.file_uploader(
                "모임 단체 사진 업로드 (최대 2장)",
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
            st.info(f"{date_str}에 저장된 사진이 아직 없습니다. 위에서 사진을 선택 후 '선택한 사진 저장하기'를 눌러주세요.")

        st.markdown("---")
        st.write("### 🙋‍♂️ 멤버별 출석 체크 (O: 출석, △: 지각/조퇴, X: 결석)")

        with st.form(key=f"form_{selected_meeting}"):
            attendance_status = {}
            for member in member_list:
                attendance_status[member] = st.radio(
                    f"{member}",
                    ["O", "△", "X"],
                    index=0,
                    horizontal=True,
                    key=f"radio_{selected_meeting}_{member}",
                )

            note = st.text_input("이번 모임 특이사항 (예: 뒷풀이 장소 등)", key=f"note_{selected_meeting}")
            submitted = st.form_submit_button("출석 기록 자동 저장")

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
            st.info("아직 기록된 출석 데이터가 없습니다. '출석 체크 및 사진' 탭에서 데이터를 먼저 입력해 주세요.")
        else:
            score_map = {"O": 1.0, "△": 0.5, "X": 0.0}
            stat_df = df.copy()
            stat_df["출석점수"] = stat_df["출석상태"].map(score_map).fillna(0.0)

            st.write(f"### 📅 {selected_meeting} 월별 출석 현황")
            monthly_df = build_monthly_grid(stat_df, member_list)
            st.dataframe(monthly_df, use_container_width=True, hide_index=True)

            st.markdown("---")

            summary_df = stat_df.groupby("이름", as_index=False)["출석점수"].sum()
            summary_df.rename(columns={"출석점수": "환산 출석 점수"}, inplace=True)

            total_meetings = stat_df["날짜"].nunique()
            summary_df["총 모임 수"] = total_meetings
            summary_df["출석률(%)"] = (summary_df["환산 출석 점수"] / total_meetings * 100).round(1)

            st.write("### 📋 멤버별 누적 출석 통계 (자동 합계)")
            st.dataframe(summary_df, use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("🎂 전체 인원 월별 생일 관리 (모임 무관)")
        st.caption(
            "모임과 관계없이 등록해 둔 모든 인원의 생일이 함께 관리되며, 앱 접속 시 오늘/다가오는 생일 알림으로 표시됩니다."
        )

        with st.form(key="global_birthday_form"):
            st.write("### ➕ 생일 등록 / 수정")
            c1, c2, c3 = st.columns([2, 2, 3])
            with c1:
                b_name = st.text_input("이름", placeholder="예: 홍길동")
            with c2:
                b_raw = st.text_input("생일 (월-일)", placeholder="예: 03-15 또는 3/15")
            with c3:
                b_memo = st.text_input("메모 (선택)", placeholder="예: 음력/양력 또는 소속")

            b_save = st.form_submit_button("💾 생일 저장")
            if b_save:
                norm_bday = normalize_mmdd(b_raw)
                if not b_name.strip():
                    st.warning("이름을 입력해 주세요.")
                elif not norm_bday:
                    st.warning("생일을 '03-15' 또는 '3/15'처럼 월과 일 형태로 입력해 주세요.")
                else:
                    upsert_birthday(b_name, norm_bday, b_memo)
                    st.success(f"'{b_name.strip()}'님의 생일({norm_bday})이 전체 생일 명단에 저장되었습니다!")
                    st.rerun()

        st.markdown("---")
        st.write("### 🗓️ 1월 ~ 12월 월별 생일자 모아보기")

        monthly_groups = {m: [] for m in range(1, 13)}
        for row in all_birthdays:
            m_num, d_num = map(int, row["birthday"].split("-"))
            monthly_groups[m_num].append((d_num, row["member_name"], row["memo"]))

        month_cols = st.columns(4)
        for m in range(1, 13):
            with month_cols[(m - 1) % 4]:
                with st.container(border=True):
                    st.markdown(f"**{m}월**")
                    entries = sorted(monthly_groups[m], key=lambda x: x[0])
                    if entries:
                        for d_num, name, memo in entries:
                            suffix = f" ({memo})" if memo else ""
                            st.write(f"• **{name}** — {m}월 {d_num}일{suffix}")
                    else:
                        st.caption("등록된 생일자 없음")

        if all_birthdays:
            st.markdown("---")
            with st.expander("📋 등록된 전체 생일 목록 및 삭제"):
                list_df = pd.DataFrame(
                    [
                        {
                            "이름": r["member_name"],
                            "생일(MM-DD)": r["birthday"],
                            "메모": r["memo"],
                        }
                        for r in all_birthdays
                    ]
                )
                st.dataframe(list_df, use_container_width=True, hide_index=True)

                del_target = st.selectbox(
                    "삭제할 인원 선택",
                    [r["member_name"] for r in all_birthdays],
                    key="del_bday_target",
                )
                if st.button("🗑️ 선택한 생일 삭제", key="btn_del_bday"):
                    delete_birthday(del_target)
                    st.success(f"'{del_target}'님의 생일 정보가 삭제되었습니다.")
                    st.rerun()
else:
    st.title("📊 통합 단체 출석부")
    render_birthday_alerts(all_birthdays, alert_days=alert_window)
    st.info("👈 왼쪽 사이드바에서 **'새 모임 만들기'**를 통해 모임을 먼저 추가해 주세요!")
