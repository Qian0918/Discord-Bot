import os
import glob
from pathlib import Path

print("=== 搜索磁盤上的所有 .db 文件 ===\n")

# 搜索常見位置
search_paths = [
    r"C:\Users\jason\Downloads\**\*.db",
    r"C:\Users\jason\Desktop\**\*.db",
    r"C:\Users\jason\Documents\**\*.db",
    r"D:\**\*.db",
]

found_files = []

for pattern in search_paths:
    results = glob.glob(pattern, recursive=True)
    for f in results:
        if "game_data" in f or "backup" in f.lower() or "raffle" in f.lower():
            found_files.append(f)
            print(f"找到: {f}")
            size = os.path.getsize(f)
            print(f"  大小: {size} bytes")
            print(f"  修改時間: {Path(f).stat().st_mtime}\n")

if not found_files:
    print("未找到相關的數據庫備份文件")
