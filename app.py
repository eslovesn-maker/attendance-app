import datetime
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from supabase import Client, create_client

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["axes.unicode_minus"] = False

st.set_page_config(page_title="통합 단체 출석부", layout="wide")


@st.cache_resource
def get_supabase_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


supabase = get_supabase_client()

if "confirm_delete" not in st.session_state:
    st.session_state.confirm_delete = False


def load_meetings() -> dict:
    res = supabase.table("meetings").select("meeting_name, members").order("meeting_name").execute()
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


st.sidebar.header("⚙️ 출석부 관리")

# 1. 새 모임 만들기 (자동 저장)
st.sidebar.subheader("➕ 새 모임 만들기")
new_meeting_name = st.sidebar.text_input("새 모임 이름 입력", placeholder="예: 31구역모임").strip()

meetings_map = load_meetings()
meeting_names = list(meetings_map.keys())

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

if meeting_names:
    selected_meeting = st.sidebar.selectbox("📂 관리할 모임 선택", meeting_names)

    # 2. 모임 이름 변경 (출석 기록도 함께 새 이름으로 이전 후 기존 행 삭제)
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
            {"members": names_input, "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        ).eq("meeting_name", selected_meeting).execute()
        st.sidebar.success("멤버 명단이 저장되었습니다!")
        st.rerun()

    member_list = [name.strip() for name in names_input.split(",") if name.strip()]
    df = load_attendance(selected_meeting)

    st.title(f"📊 {selected_meeting} 통합 출석부")
    tab1, tab2 = st.tabs(["📝 출석 체크 및 사진", "📈 연간 출석 현황 및 추이"])

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
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=True,
                key=f"photo_{selected_meeting}",
            )

        if group_photos:
            st.write("📷 **업로드된 모임 사진 미리보기**")
            photo_cols = st.columns(2)
            for idx, photo in enumerate(group_photos[:2]):
                with photo_cols[idx]:
                    st.image(photo, caption=f"사진 {idx+1} ({meeting_date})", use_container_width=True)

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
                date_str = str(meeting_date)
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
        st.subheader(f"📈 '{selected_meeting}' 연간 출석 현황 및 추이")
        if df.empty:
            st.info("아직 기록된 출석 데이터가 없습니다. '출석 체크 및 사진' 탭에서 데이터를 먼저 입력해 주세요.")
        else:
            score_map = {"O": 1.0, "△": 0.5, "X": 0.0}
            stat_df = df.copy()
            stat_df["출석점수"] = stat_df["출석상태"].map(score_map).fillna(0.0)

            summary_df = stat_df.groupby("이름", as_index=False)["출석점수"].sum()
            summary_df.rename(columns={"출석점수": "환산 출석 점수"}, inplace=True)

            total_meetings = stat_df["날짜"].nunique()
            summary_df["총 모임 수"] = total_meetings
            summary_df["출석률(%)"] = (summary_df["환산 출석 점수"] / total_meetings * 100).round(1)

            st.write("### 📋 멤버별 누적 출석 통계 (자동 합계)")
            st.dataframe(summary_df, use_container_width=True)

            st.write("### 📊 날짜별 전체 참석 점수 추이")
            trend_df = stat_df.groupby("날짜", as_index=False)["출석점수"].sum()

            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(
                trend_df["날짜"],
                trend_df["출석점수"],
                marker="o",
                color="#4F46E5",
                linewidth=2,
                markersize=8,
            )
            ax.set_title(f"[{selected_meeting}] 시간에 따른 모임 참석 점수 추이", fontsize=12, fontweight="bold")
            ax.set_xlabel("모임 날짜")
            ax.set_ylabel("참석 점수 합계 (O=1, △=0.5)")
            ax.grid(True, linestyle="--", alpha=0.6)
            plt.xticks(rotation=45)
            st.pyplot(fig)
else:
    st.title("📊 통합 단체 출석부")
    st.info("👈 왼쪽 사이드바에서 **'새 모임 만들기'**를 통해 모임을 먼저 추가해 주세요!")
