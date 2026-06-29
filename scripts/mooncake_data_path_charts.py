#!/usr/bin/env python3
"""画 4 张 Mooncake 多层 KV cache data path 架构图

风格:深色 #1f1f1f 背景 + 高对比色 + Noto Sans CJK 中英兼容
"""
import os, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.font_manager as fm

# Font setup
plt.rcParams['font.family'] = ['Noto Sans CJK JP', 'Noto Sans CJK SC', 'DejaVu Sans']
plt.rcParams['font.size'] = 11
plt.rcParams['figure.facecolor'] = '#1f1f1f'
plt.rcParams['axes.facecolor'] = '#1f1f1f'
plt.rcParams['savefig.facecolor'] = '#1f1f1f'
plt.rcParams['text.color'] = 'white'
plt.rcParams['axes.labelcolor'] = 'white'
plt.rcParams['xtick.color'] = 'white'
plt.rcParams['ytick.color'] = 'white'
plt.rcParams['axes.edgecolor'] = '#444'
plt.rcParams['axes.spines.top'] = False
plt.rcParams['axes.spines.right'] = False
for fp in ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
           '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc']:
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)

OUT_DIR = '/home/ficus/llm/storage/docs/mooncake-source-research/charts'
os.makedirs(OUT_DIR, exist_ok=True)

# Color palette
COLOR_GPU   = '#ff006e'  # 品红
COLOR_HOST  = '#fb5607'  # 橙红
COLOR_REMOTE= '#ffbe0b'  # 黄
COLOR_SSD   = '#00e5ff'  # 青
COLOR_BORDER= '#666666'
COLOR_TEXT  = 'white'
COLOR_DIM   = '#cccccc'

# ============================================================
# Figure 1: 4-Tier Cache Hierarchy
# ============================================================
fig, ax = plt.subplots(figsize=(11, 9))
ax.set_xlim(0, 10)
ax.set_ylim(0, 11)
ax.set_axis_off()

tiers = [
    dict(y=8.5, name='Tier 1: GPU VRAM (L1 Cache)',
         desc='Managed by inference engine (SGLang/vLLM)',
         bullets=['• Latency: < 1 μs (fastest)',
                  '• Capacity: 16-80 GB per GPU',
                  '• Access: kernel launches, attention'],
         color=COLOR_GPU),
    dict(y=6.3, name='Tier 2: Host DRAM (L2 Cache - HiCache)',
         desc='CPU-accessible pinned memory',
         bullets=['• Latency: ~10 μs',
                  '• Capacity: 100-500 GB per node',
                  '• Access: radix tree, mmapped'],
         color=COLOR_HOST),
    dict(y=4.1, name='Tier 3: Remote DRAM Pool (Mooncake Store)',
         desc='Distributed across cluster nodes',
         bullets=['• Latency: ~50-100 μs (RDMA)',
                  '• Capacity: TBs (elastic)',
                  '• Access: Transfer Engine + RDMA'],
         color=COLOR_REMOTE),
    dict(y=1.9, name='Tier 4: Local NVMe SSD (FileStorage)',
         desc='Persistent local storage',
         bullets=['• Latency: 1-5 ms',
                  '• Capacity: Multi-TB per node',
                  '• Access: io_uring/pwritev/preadv'],
         color=COLOR_SSD),
]

for t in tiers:
    box = FancyBboxPatch((0.5, t['y']-0.7), 9, 1.4,
                          boxstyle='round,pad=0.05,rounding_size=0.1',
                          facecolor=t['color'], alpha=0.15,
                          edgecolor=t['color'], linewidth=2)
    ax.add_patch(box)
    ax.text(0.7, t['y']+0.35, t['name'], fontsize=15, fontweight='bold',
            color=t['color'], va='center')
    ax.text(0.7, t['y']+0.05, t['desc'], fontsize=10, color=COLOR_DIM, va='center')
    ax.text(0.7, t['y']-0.35, '  '.join(t['bullets']), fontsize=9, color=COLOR_TEXT, va='center')

# Arrows between tiers
for y_from, y_to, label in [
    (7.8, 7.0, '↓ cudaMemcpy (eviction)  ↑ cudaMemcpy (promotion)'),
    (5.6, 4.8, '↓ RDMA send (eviction)  ↑ RDMA recv (fetch)'),
    (3.4, 2.6, '↓ pwritev/io_uring (offload)  ↑ preadv/io_uring (promotion)'),
]:
    ax.annotate('', xy=(5, y_to), xytext=(5, y_from),
                arrowprops=dict(arrowstyle='<->', color='white', lw=2))
    ax.text(5.3, (y_from + y_to)/2, label, fontsize=10, color='white', va='center',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#1f1f1f', edgecolor='white'))

ax.set_title('Mooncake 4-Tier Cache Hierarchy',
             fontsize=18, fontweight='bold', pad=15, color='white')
plt.tight_layout()
plt.savefig(f'{OUT_DIR}/01_four_tier_cache_hierarchy.png', dpi=130, bbox_inches='tight')
plt.close()
print('saved 01_four_tier_cache_hierarchy.png')

# ============================================================
# Figure 2: Data Path Overview — SSD Offload vs RDMA Promotion
# ============================================================
fig, ax = plt.subplots(figsize=(13, 7.5))
ax.set_xlim(0, 13)
ax.set_ylim(0, 8)
ax.set_axis_off()

# Left column: SSD Offload (本地写路径)
ax.text(6.5, 7.5, 'Mooncake KV Cache Data Path Overview',
        fontsize=18, fontweight='bold', ha='center', color='white')
ax.text(6.5, 7.05, 'SSD Offload (Prefill) + RDMA Promotion (Decode)',
        fontsize=12, ha='center', color=COLOR_DIM)

# 4 horizontal tiers
boxes = [
    dict(y=5.0, x=0.5, w=12.0, name='GPU VRAM',
         desc='SGLang/vLLM KV cache',
         color=COLOR_GPU),
    dict(y=3.5, x=0.5, w=12.0, name='Host DRAM (HiCache / Mooncake Pool)',
         desc='CPU pinned memory',
         color=COLOR_HOST),
    dict(y=2.0, x=0.5, w=12.0, name='Local NVMe SSD OR Remote DRAM Pool',
         desc='Persistent / distributed',
         color=COLOR_REMOTE),
    dict(y=0.5, x=0.5, w=12.0, name='NVMe-oF / Remote Node SSD',
         desc='Optional extension (GDS only on this path)',
         color=COLOR_SSD),
]
for b in boxes:
    box = FancyBboxPatch((b['x'], b['y']), b['w'], 1.0,
                          boxstyle='round,pad=0.05,rounding_size=0.1',
                          facecolor=b['color'], alpha=0.15,
                          edgecolor=b['color'], linewidth=2)
    ax.add_patch(box)
    ax.text(b['x']+b['w']/2, b['y']+0.65, b['name'], fontsize=13, fontweight='bold',
            color=b['color'], ha='center', va='center')
    ax.text(b['x']+b['w']/2, b['y']+0.25, b['desc'], fontsize=9, color=COLOR_DIM,
            ha='center', va='center')

# SSD Offload arrow (left side, downward)
ax.annotate('', xy=(2.5, 3.5), xytext=(2.5, 5.0),
            arrowprops=dict(arrowstyle='->', color=COLOR_HOST, lw=3))
ax.text(2.0, 4.25, 'cudaMemcpy\nD→H', fontsize=10, color=COLOR_HOST, ha='right')

ax.annotate('', xy=(2.5, 2.0), xytext=(2.5, 3.5),
            arrowprops=dict(arrowstyle='->', color=COLOR_REMOTE, lw=3))
ax.text(2.0, 2.75, 'io_uring\nbatch write', fontsize=10, color=COLOR_REMOTE, ha='right')

ax.annotate('', xy=(2.5, 0.5), xytext=(2.5, 2.0),
            arrowprops=dict(arrowstyle='->', color=COLOR_SSD, lw=3, linestyle='--', alpha=0.5))
ax.text(2.0, 1.25, 'NVMe-oF\n(GDS only)', fontsize=10, color=COLOR_SSD, ha='right', alpha=0.7)

# Decode Promotion arrow (right side, upward)
ax.annotate('', xy=(10.5, 5.0), xytext=(10.5, 3.5),
            arrowprops=dict(arrowstyle='->', color=COLOR_GPU, lw=3))
ax.text(11.0, 4.25, 'cudaMemcpy\nH→D', fontsize=10, color=COLOR_GPU, ha='left')

ax.annotate('', xy=(10.5, 3.5), xytext=(10.5, 2.0),
            arrowprops=dict(arrowstyle='->', color=COLOR_REMOTE, lw=3))
ax.text(11.0, 2.75, 'io_uring\nbatch read', fontsize=10, color=COLOR_REMOTE, ha='left')

ax.annotate('', xy=(10.5, 2.0), xytext=(10.5, 0.5),
            arrowprops=dict(arrowstyle='->', color=COLOR_SSD, lw=3, linestyle='--', alpha=0.5))
ax.text(11.0, 1.25, 'NVMe-oF\npromote', fontsize=10, color=COLOR_SSD, ha='left', alpha=0.7)

# Center annotations
ax.text(6.5, 5.5, 'Solid arrows = production path (cudaMemcpy + io_uring)',
        fontsize=10, color='white', ha='center',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#333', edgecolor=COLOR_HOST))
ax.text(6.5, 4.7, 'Dashed arrows = GPUDirect Storage only available on NVMe-oF path',
        fontsize=10, color=COLOR_DIM, ha='center', style='italic',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#333', edgecolor=COLOR_SSD))

# Side labels
ax.text(0.3, 6.0, 'Prefill\n(写)', fontsize=11, color=COLOR_HOST, rotation=90,
        ha='center', va='center', fontweight='bold')
ax.text(12.7, 6.0, 'Decode\n(读)', fontsize=11, color=COLOR_GPU, rotation=270,
        ha='center', va='center', fontweight='bold')

plt.tight_layout()
plt.savefig(f'{OUT_DIR}/02_data_path_overview.png', dpi=130, bbox_inches='tight')
plt.close()
print('saved 02_data_path_overview.png')

# ============================================================
# Figure 3: GPUDirect Storage Investigation — Why NOT Used
# ============================================================
fig, ax = plt.subplots(figsize=(13, 7.5))
ax.set_xlim(0, 13)
ax.set_ylim(0, 8)
ax.set_axis_off()
ax.set_title('GPUDirect Storage Investigation — Production Path Does NOT Use GDS',
             fontsize=15, fontweight='bold', pad=10, color='white')

# Left side: Production path (cudaMemcpy + io_uring)
ax.text(3.5, 7.2, 'Production SSD Offload', fontsize=14, fontweight='bold',
        ha='center', color=COLOR_GPU)
ax.text(3.5, 6.75, '(actual code path)', fontsize=10, color=COLOR_DIM, ha='center', style='italic')

nodes_left = [
    (5.8, 'GPU VRAM', COLOR_GPU, '<1 μs'),
    (4.5, 'Host Pinned Memory', COLOR_HOST, '~10 μs'),
    (3.2, 'NVMe SSD', COLOR_REMOTE, '1-5 ms'),
]
for y, name, color, lat in nodes_left:
    box = FancyBboxPatch((1.5, y-0.4), 4, 0.8,
                          boxstyle='round,pad=0.05,rounding_size=0.1',
                          facecolor=color, alpha=0.15, edgecolor=color, linewidth=2)
    ax.add_patch(box)
    ax.text(3.5, y, name, fontsize=12, fontweight='bold', color=color,
            ha='center', va='center')
    ax.text(3.5, y-0.18, lat, fontsize=9, color=COLOR_DIM, ha='center', va='center')

# 2 arrows
ax.annotate('', xy=(3.5, 4.9), xytext=(3.5, 5.4),
            arrowprops=dict(arrowstyle='->', color=COLOR_HOST, lw=2.5))
ax.text(2.0, 5.15, 'cudaMemcpy\nD→H\n(1 copy)', fontsize=9, color=COLOR_HOST,
        ha='center', va='center')

ax.annotate('', xy=(3.5, 3.6), xytext=(3.5, 4.1),
            arrowprops=dict(arrowstyle='->', color=COLOR_REMOTE, lw=2.5))
ax.text(2.0, 3.85, 'io_uring\nbatch write\n(zero-copy)', fontsize=9, color=COLOR_REMOTE,
        ha='center', va='center')

ax.text(3.5, 2.0, '2 copies total\n(GPU→Host explicit)', fontsize=11, color=COLOR_GPU,
        ha='center', fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='#333', edgecolor=COLOR_GPU))

# Right side: GDS alternative (theoretical)
ax.text(9.5, 7.2, 'GDS-Enabled Path (theoretical)', fontsize=14, fontweight='bold',
        ha='center', color=COLOR_SSD)
ax.text(9.5, 6.75, '(NOT implemented in production)', fontsize=10, color=COLOR_DIM, ha='center', style='italic')

nodes_right = [
    (5.8, 'GPU VRAM', COLOR_GPU, '<1 μs'),
    (3.2, 'NVMe SSD (via GDS)', COLOR_SSD, '1-5 ms'),
]
for y, name, color, lat in nodes_right:
    box = FancyBboxPatch((7.5, y-0.4), 4, 0.8,
                          boxstyle='round,pad=0.05,rounding_size=0.1',
                          facecolor=color, alpha=0.15, edgecolor=color, linewidth=2)
    ax.add_patch(box)
    ax.text(9.5, y, name, fontsize=12, fontweight='bold', color=color,
            ha='center', va='center')
    ax.text(9.5, y-0.18, lat, fontsize=9, color=COLOR_DIM, ha='center', va='center')

ax.annotate('', xy=(9.5, 3.6), xytext=(9.5, 5.4),
            arrowprops=dict(arrowstyle='->', color=COLOR_SSD, lw=2.5, linestyle='--', alpha=0.6))
ax.text(11.4, 4.5, 'cuFile\n(no host copy)\n(NOT IMPL)', fontsize=9, color=COLOR_SSD,
        ha='center', va='center', style='italic', alpha=0.6)

ax.text(9.5, 2.0, '1 copy theoretically\n(NOT implemented)', fontsize=11, color=COLOR_SSD,
        ha='center', fontweight='bold', style='italic', alpha=0.7,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='#333', edgecolor=COLOR_SSD))

# Bottom: reasons not to use GDS
ax.text(6.5, 1.1, 'Why NOT GDS for local SSD:', fontsize=11, fontweight='bold',
        ha='center', color='white')
ax.text(6.5, 0.65, '(1) KV cache is staged in Host DRAM for HiCache L2 anyway   (2) GDS requires GPU-resident objects',
        fontsize=9, color=COLOR_DIM, ha='center')
ax.text(6.5, 0.35, '(3) Explicit cudaMemcpy gives finer batch control   (4) GDS only optimizes GPU-resident data',
        fontsize=9, color=COLOR_DIM, ha='center')

plt.tight_layout()
plt.savefig(f'{OUT_DIR}/03_gpudirect_storage_investigation.png', dpi=130, bbox_inches='tight')
plt.close()
print('saved 03_gpudirect_storage_investigation.png')

# ============================================================
# Figure 4: Zero-Copy Boundaries — Where copies happen
# ============================================================
fig, ax = plt.subplots(figsize=(13, 7))
ax.set_xlim(0, 13)
ax.set_ylim(0, 7)
ax.set_axis_off()
ax.set_title('Zero-Copy Boundaries — Where Memory Copies Happen',
             fontsize=15, fontweight='bold', pad=10, color='white')

# 4 boxes in a row representing memory regions
regions = [
    (1.5, 'GPU VRAM', COLOR_GPU, '<1 μs'),
    (4.5, 'Host Pinned\nDRAM', COLOR_HOST, '~10 μs'),
    (7.5, 'NVMe SSD\n(O_DIRECT)', COLOR_REMOTE, '1-5 ms'),
    (10.5, 'Remote DRAM\n(RDMA)', COLOR_SSD, '~50 μs'),
]
for x, name, color, lat in regions:
    box = FancyBboxPatch((x-1.0, 4.5), 2.0, 1.6,
                          boxstyle='round,pad=0.05,rounding_size=0.1',
                          facecolor=color, alpha=0.2, edgecolor=color, linewidth=2.5)
    ax.add_patch(box)
    ax.text(x, 5.5, name, fontsize=12, fontweight='bold', color=color,
            ha='center', va='center')
    ax.text(x, 4.85, lat, fontsize=10, color=COLOR_DIM, ha='center', va='center')

# Boundaries and copy operations
boundaries = [
    # (from_x, to_x, y, label, type)
    (2.5, 3.5, 3.4, 'cudaMemcpy\nD↔H\n(1 explicit copy)', 'copy'),
    (5.5, 6.5, 3.4, 'io_uring\nwritev/readv\n(zero-copy)', 'zerocopy'),
    (8.5, 9.5, 3.4, 'RDMA\nsend/recv\n(zero-copy)', 'zerocopy'),
    (9.5, 10.5, 2.2, 'NVMe-oF\n+ GDS available\n(NOT used locally)', 'unused'),
]

for fx, tx, y, label, btype in boundaries:
    if btype == 'copy':
        color = COLOR_GPU
        style = '->'
        ax.annotate('', xy=(tx, y+0.3), xytext=(fx, y+0.3),
                    arrowprops=dict(arrowstyle='<->', color=color, lw=2.5))
    elif btype == 'zerocopy':
        color = '#00ff88'
        style = '<->'
        ax.annotate('', xy=(tx, y+0.3), xytext=(fx, y+0.3),
                    arrowprops=dict(arrowstyle='<->', color=color, lw=2.5))
    elif btype == 'unused':
        color = COLOR_SSD
        style = '--'
        ax.annotate('', xy=(tx, y-0.3), xytext=(fx, y-0.3),
                    arrowprops=dict(arrowstyle='<->', color=color, lw=2, linestyle='--', alpha=0.5))
    ax.text((fx+tx)/2, y+0.3, label, fontsize=9, color=color, ha='center', va='bottom',
            fontweight='bold')

# Legend at bottom
ax.text(0.5, 1.5, 'Legend:', fontsize=11, fontweight='bold', color='white')
legend_items = [
    (1.5, 'cudaMemcpy\n(1 copy)', COLOR_GPU),
    (4.5, 'io_uring\n(zero-copy)', '#00ff88'),
    (7.5, 'RDMA\n(zero-copy)', '#00ff88'),
    (10.0, 'GDS only on\nNVMe-oF (unused)', COLOR_SSD),
]
for x, lbl, color in legend_items:
    ax.add_patch(FancyBboxPatch((x-0.5, 0.3), 1.6, 0.8,
                                 boxstyle='round,pad=0.02',
                                 facecolor=color, alpha=0.3, edgecolor=color, linewidth=1.5))
    ax.text(x+0.3, 0.7, lbl, fontsize=9, color=color, ha='center', va='center', fontweight='bold')

ax.text(6.5, -0.2, 'Key insight: Only 1 explicit copy (GPU↔Host). All other boundaries are zero-copy.',
        fontsize=11, color='white', ha='center', style='italic',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#333', edgecolor='white'))

plt.tight_layout()
plt.savefig(f'{OUT_DIR}/04_zero_copy_boundaries.png', dpi=130, bbox_inches='tight')
plt.close()
print('saved 04_zero_copy_boundaries.png')

print('\n=== 全部完成 ===')
print(f'4 PNG files in {OUT_DIR}')