"""일별 이벤트 수 추이 그림 생성 (한글 폰트 확인 포함)."""
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

KOREAN_FONT = "AppleGothic"
plt.rcParams["font.family"] = KOREAN_FONT
plt.rcParams["axes.unicode_minus"] = False

TABLES = {
    "product_buy": "구매",
    "add_to_cart": "장바구니 담기",
    "remove_from_cart": "장바구니 제거",
    "page_visit": "페이지 방문",
    "search_query": "검색",
}

fig, axes = plt.subplots(len(TABLES), 1, figsize=(11, 3 * len(TABLES)), sharex=True)
for ax, (table, label_ko) in zip(axes, TABLES.items()):
    df = pd.read_csv(f"data/processed/daily_{table}.csv", parse_dates=["day"])
    ax.plot(df["day"], df["n"], linewidth=1)
    ax.set_title(f"{table} ({label_ko}) 일별 이벤트 수")
    ax.set_ylabel("건수")
    ax.grid(alpha=0.3)

axes[-1].set_xlabel("날짜")
fig.suptitle("테이블별 일별 이벤트 수 추이 (2022-06-23 ~ 2022-12-08)", y=1.0, fontsize=13)
fig.tight_layout(rect=[0, 0, 1, 0.98])
fig.savefig("docs/figures/daily_event_counts.png", dpi=150)
print("saved docs/figures/daily_event_counts.png")

# 폰트 깨짐 확인용 샘플 (한글 텍스트가 사각형(□)으로 안 깨지는지 렌더링 체크)
fig2, ax2 = plt.subplots(figsize=(4, 1.5))
ax2.text(0.5, 0.5, "한글 폰트 확인: 구매, 장바구니, 검색", ha="center", va="center", fontsize=12)
ax2.axis("off")
fig2.savefig("docs/figures/font_check.png", dpi=150)
print("saved docs/figures/font_check.png")
print("used font:", KOREAN_FONT, "available:", KOREAN_FONT in {f.name for f in fm.fontManager.ttflist})
