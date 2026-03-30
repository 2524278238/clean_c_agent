import os
import datetime

path = r"C:\Users\lyt\a"

print(f"Testing path: {path}")
print(f"Exists: {os.path.exists(path)}")
print(f"Is dir: {os.path.isdir(path)}")

items = []
try:
    with os.scandir(path) as it:
        for entry in it:
            try:
                stat = entry.stat(follow_symlinks=False)
                size = stat.st_size if entry.is_file(follow_symlinks=False) else 0
                mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                item_type = "文件夹" if entry.is_dir(follow_symlinks=False) else "文件"
                items.append(f"- {entry.name} ({item_type}, 大小: {size} 字节, 修改时间: {mtime})")
            except Exception as inner_e:
                print(f"Error reading entry {entry.name}: {inner_e}")
                
    print(f"Successfully read {len(items)} items.")
    for i in items[:5]:
        print(i)
except Exception as e:
    print(f"Error with os.scandir: {e}")
