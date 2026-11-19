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
