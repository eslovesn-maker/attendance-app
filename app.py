import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import datetime

# 한글 폰트 깨짐 방지
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False

st.set_page_config(page_title="통합 단체 출석부", layout="wide")

# 1. 세션 상태 초기화 (가장 먼저 실행되어야 에러가 안 납니다!)
if "meetings" not in st.session_state:
    st.session_state.meetings = {}

st.sidebar.header("⚙️ 출석부 관리")

# 2. 새 모임 만들기 기능
st.sidebar.subheader("➕ 새 모임 만들기")
new_meeting_name = st.sidebar.text_input("새 모임 이름 입력", placeholder="예: 31구역모임")
if st.sidebar.button("모임 추가하기"):
    if new_meeting_name and new_meeting_name not in st.session_state.meetings:
        st.session_state.meetings[new_meeting_name] = {
            "members": "참가자1, 참가자2",
            "data": pd.DataFrame(columns=["날짜", "이름", "출석상태", "비고"])
        }
        st.sidebar.success(f"'{new_meeting_name}' 모임이 생성되었습니다!")
        st.rerun()
    elif new_meeting_name in st.session_state.meetings:
        st.sidebar.warning("이미 존재하는 모임 이름입니다.")

st.sidebar.markdown("---")

# 3. 현재 존재하는 모임 목록 가져오기 및 관리
meeting_names = list(st.session_state.meetings.keys())

if meeting_names:
    selected_meeting = st.sidebar.selectbox("📂 관리할 모임 선택", meeting_names)
    
    # 모임 이름 변경 기능
    new_name = st.sidebar.text_input("선택한 모임 새 이름 변경", value=selected_meeting)
    if st.sidebar.button("이름 변경하기"):
        if new_name and new_name not in st.session_state.meetings:
            st.session_state.meetings[new_name] = st.session_state.meetings.pop(selected_meeting)
            st.rerun()
            
    # 모임 삭제 기능
    if st.sidebar.button("현재 모임 삭제하기"):
        del st.session_state.meetings[selected_meeting]
        st.rerun()
        
    st.sidebar.markdown("---")
    
    # 선택된 모임의 데이터 및 멤버 설정 가져오기
    current_meeting = st.session_state.meetings[selected_meeting]
    
    st.sidebar.subheader(f"👥 [{selected_meeting}] 멤버 설정")
    names_input = st.sidebar.text_area("참석자 명단 수정 (쉼표로 구분)", current_meeting["members"])
    current_meeting["members"] = names_input
    member_list = [name.strip() for name in names_input.split(",") if name.strip()]

    # 메인 화면 제목
    st.title(f"📊 {selected_meeting} 통합 출석부")

    # 탭 메뉴 구성
    tab1, tab2, tab3 = st.tabs(["📝 출석 체크 및 사진", "📈 연간 출석 현황 및 추이", "💾 데이터 관리"])

    with tab1:
        st.subheader(f"'{selected_meeting}' 모임 출석 입력")
        
        col1, col2 = st.columns(2)
        with col1:
            meeting_date = st.date_input("모임 날짜 선택", datetime.date.today(), key=f"date_{selected_meeting}")
        with col2:
            group_photos = st.file_uploader(
                "모임 단체 사진 업로드 (최대 2장)", 
                type=["png", "jpg", "jpeg"], 
                accept_multiple_files=True,
                key=f"photo_{selected_meeting}"
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
                    key=f"radio_{selected_meeting}_{member}"
                )
            
            note = st.text_input("이번 모임 특이사항 (예: 뒷풀이 장소 등)", key=f"note_{selected_meeting}")
            submitted = st.form_submit_button("출석 기록 저장")
            
            if submitted:
                new_records = []
                for member, status in attendance_status.items():
                    new_records.append({
                        "날짜": str(meeting_date),
                        "이름": member,
                        "출석상태": status,
                        "비고": note
                    })
                
                new_df = pd.DataFrame(new_records)
                df_existing = current_meeting["data"]
                current_meeting["data"] = pd.concat([
                    df_existing[df_existing["날짜"] != str(meeting_date)],
                    new_df
                ], ignore_index=True)
                st.success(f"'{selected_meeting}'의 {meeting_date} 출석 기록이 저장되었습니다!")

    with tab2:
        st.subheader(f"📈 '{selected_meeting}' 연간 출석 현황 및 추이")
        df = current_meeting["data"]
        
        if df.empty:
            st.info("아직 기록된 출석 데이터가 없습니다. '출석 체크 및 사진' 탭에서 데이터를 먼저 입력해 주세요.")
        else:
            def get_score(status):
                if status == "O": return 1.0
                elif status == "△": return 0.5
                else: return 0.0

            df["출석점수"] = df["출석상태"].apply(get_score)
            summary_df = df.groupby("이름")["출석점수"].sum().reset_index()
            summary_df.rename(columns={"출석점수": "환산 출석 점수"}, inplace=True)
            
            total_meetings = df["날짜"].nunique()
            summary_df["총 모임 수"] = total_meetings
            summary_df["출석률(%)"] = (summary_df["환산 출석 점수"] / total_meetings * 100).round(1)
            
            st.write("### 📋 멤버별 누적 출석 통계 (자동 합계)")
            st.dataframe(summary_df, use_container_width=True)
            
            st.write("### 📊 날짜별 전체 참석 점수 추이")
            trend_df = df.groupby("날짜")["출석점수"].sum().reset_index()
            
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(trend_df["날짜"], trend_df["출석점수"], marker='o', color='#4F46E5', linewidth=2, markersize=8)
            ax.set_title(f"[{selected_meeting}] 시간에 따른 모임 참석 점수 추이", fontsize=12, fontweight='bold')
            ax.set_xlabel("모임 날짜")
            ax.set_ylabel("참석 점수 합계 (O=1, △=0.5)")
            ax.grid(True, linestyle='--', alpha=0.6)
            plt.xticks(rotation=45)
            st.pyplot(fig)

    with tab3:
        st.subheader(f"💾 '{selected_meeting}' 데이터 백업 및 관리")
        df = current_meeting["data"]
        
        if not df.empty:
            st.write("현재 저장된 전체 데이터:")
            st.dataframe(df, use_container_width=True)
            
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label=f"'{selected_meeting}' 출석부 엑셀(CSV) 다운로드",
                data=csv,
                file_name=f"{selected_meeting}_attendance.csv",
                mime="text/csv",
            )
        else:
            st.info("다운로드할 데이터가 없습니다.")
else:
    st.title("📊 통합 단체 출석부")
    st.info("👈 왼쪽 사이드바에서 **'새 모임 만들기'**를 통해 모임을 먼저 추가해 주세요!")
