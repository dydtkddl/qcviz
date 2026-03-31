import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── 설정 ──
fig, ax = plt.subplots(figsize=(14, 3.2))
fig.patch.set_facecolor('#FFFFFF')
ax.set_facecolor('#FFFFFF')

# ── 데이터 ──
labels = [
    'Find a\ncomputation\nperson',
    'Structure\npreparation',
    'Input file\nwriting',
    'Calculation\nsetup',
    'Run\ncalculation',
    'Output\nparsing',
    'Visualization\n& interpretation'
]
widths = [12, 15, 14, 12, 15, 16, 16]  # 비율 (합=100)
colors = [
    '#FF4C4C',  # 빨강 계열 - overhead
    '#FF6B6B',
    '#FF8585',
    '#FF9E9E',
    '#00E5A0',  # 민트/초록 - actual calc
    '#FFB347',  # 주황 계열 - overhead
    '#FFCC66',
]

overhead_color = '#FF4C4C'
calc_color = '#00E5A0'

# 실제 색상: 계산만 초록, 나머지 빨강 그라데이션
bar_colors = ['#FF4C4C', '#FF5C5C', '#FF6B6B', '#FF7A7A', '#00E5A0', '#FF8C42', '#FFB347']

# ── 스택 바 그리기 ──
bar_height = 0.6
y_center = 0.5
left = 0

rects = []
for i, (w, c) in enumerate(zip(widths, bar_colors)):
    rect = ax.barh(y_center, w, left=left, height=bar_height, color=c,
                   edgecolor='#0D1B2A', linewidth=1.5, zorder=3)
    rects.append((left, w))

    # 라벨
    cx = left + w / 2
    fontsize = 7.5 if i != 4 else 8.5
    fontweight = 'bold' if i == 4 else 'normal'
    txt_color = '#FFFFFF' if i != 4 else '#0D1B2A'
    ax.text(cx, y_center, labels[i], ha='center', va='center',
            fontsize=fontsize, fontweight=fontweight, color=txt_color,
            linespacing=1.2, zorder=5)

    # 상단에 비율 표시
    ax.text(cx, y_center + 0.38, f'{w}%', ha='center', va='bottom',
            fontsize=8, color='#8899AA', fontweight='medium', zorder=5)

    left += w

# ── 브래킷 & 주석 ──
# Overhead 구간 (0~54, 69~100)
overhead_total = sum(widths[:4]) + sum(widths[5:])

# 상단 타이틀
ax.text(50, y_center + 0.58, 'TIME DISTRIBUTION — Typical Quantum Chemistry Workflow',
        ha='center', va='bottom', fontsize=11, fontweight='bold',
        color='#FFFFFF', zorder=5)

# 하단 주석 바
# Overhead bar
ax.barh(-0.15, sum(widths[:4]), left=0, height=0.12,
        color='#FF4C4C', alpha=0.4, zorder=3)
ax.barh(-0.15, sum(widths[5:]), left=sum(widths[:5]), height=0.12,
        color='#FF4C4C', alpha=0.4, zorder=3)
# Calc bar
ax.barh(-0.15, widths[4], left=sum(widths[:4]), height=0.12,
        color='#00E5A0', alpha=0.4, zorder=3)

# 하단 텍스트
ax.text(sum(widths[:4]) / 2, -0.38,
        f'Manual overhead: ~{sum(widths[:4])}%',
        ha='center', va='top', fontsize=8.5, color='#FF8585', fontstyle='italic', zorder=5)

ax.text(sum(widths[:4]) + widths[4] / 2, -0.38,
        f'Actual calc: {widths[4]}%',
        ha='center', va='top', fontsize=8.5, color='#00E5A0', fontweight='bold', zorder=5)

ax.text(sum(widths[:5]) + sum(widths[5:]) / 2, -0.38,
        f'Post-processing overhead: ~{sum(widths[5:])}%',
        ha='center', va='top', fontsize=8.5, color='#FFB347', fontstyle='italic', zorder=5)

# 큰 메시지
ax.text(50, -0.62,
        'Only 1 of 7 steps is actual computation — the rest is manual overhead',
        ha='center', va='top', fontsize=10, fontweight='bold',
        color='#FFD700', zorder=5)

# ── 축 정리 ──
ax.set_xlim(0, 100)
ax.set_ylim(-0.85, 1.1)
ax.axis('off')

# ── 범례 ──
legend_elements = [
    mpatches.Patch(facecolor='#FF4C4C', edgecolor='none', label='Manual overhead (pre-calc)'),
    mpatches.Patch(facecolor='#00E5A0', edgecolor='none', label='Actual QC calculation'),
    mpatches.Patch(facecolor='#FFB347', edgecolor='none', label='Manual overhead (post-calc)'),
]
leg = ax.legend(handles=legend_elements, loc='upper right',
                fontsize=7.5, frameon=True, facecolor='#1B2838',
                edgecolor='#334455', labelcolor='#CCDDEE',
                bbox_to_anchor=(1.0, 1.15))

plt.tight_layout()
plt.savefig('time_distribution.png', dpi=300, bbox_inches='tight',
            facecolor='#0D1B2A', edgecolor='none')
plt.show()


