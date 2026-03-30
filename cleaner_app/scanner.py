import os
import getpass
from pathlib import Path

def get_size(path):
    total_size = 0
    if os.path.isfile(path):
        total_size = os.path.getsize(path)
    elif os.path.isdir(path):
        try:
            for dirpath, _, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if not os.path.islink(fp):
                        total_size += os.path.getsize(fp)
        except Exception:
            pass
    return total_size

def format_size(size_bytes):
    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while size_bytes >= 1024 and i < len(size_name) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.2f} {size_name[i]}"

class Scanner:
    def __init__(self, large_file_threshold_mb=500):
        self.user = getpass.getuser()
        self.home = str(Path.home())
        self.large_file_threshold_mb = large_file_threshold_mb
        
    def scan_all(self, progress_callback=None):
        results = []
        
        # 0. 常规系统清理 (Temp, Update Cache)
        sys_caches = []
        # %TEMP% (用户临时文件夹)
        temp_dir = os.environ.get('TEMP')
        if temp_dir and os.path.exists(temp_dir):
            sys_caches.append(("用户临时文件 (%TEMP%)", temp_dir))
        
        # C:\Windows\Temp (系统临时文件夹)
        win_temp = os.path.join("C:\\", "Windows", "Temp")
        if os.path.exists(win_temp):
            sys_caches.append(("系统临时文件 (Windows/Temp)", win_temp))
            
        # 系统更新缓存 (SoftwareDistribution)
        update_cache = os.path.join("C:\\", "Windows", "SoftwareDistribution", "Download")
        if os.path.exists(update_cache):
            sys_caches.append(("系统更新缓存 (SoftwareDistribution)", update_cache))
            
        cat_sys = {"category": "常规系统清理", "items": []}
        for name, path in sys_caches:
            if progress_callback: progress_callback(f"正在扫描: {path}")
            size = get_size(path)
            if size > 0:
                cat_sys["items"].append({"name": name, "path": path, "size": size, "type": "dir", "checked_by_default": True})
        if cat_sys["items"]:
            results.append(cat_sys)
        
        # 1. Developer Caches
        dev_caches = [
            ("pip 缓存", os.path.join(self.home, "AppData", "Local", "pip", "Cache")),
            ("npm 缓存", os.path.join(self.home, "AppData", "Local", "npm-cache")),
            ("NVIDIA 缓存", os.path.join(self.home, "AppData", "Local", "NVIDIA", "GLCache")),
        ]
        
        cat_dev = {"category": "开发者与系统缓存", "items": []}
        for name, path in dev_caches:
            if os.path.exists(path):
                if progress_callback: progress_callback(f"正在扫描: {path}")
                size = get_size(path)
                if size > 0:
                    cat_dev["items"].append({"name": name, "path": path, "size": size, "type": "dir", "checked_by_default": True})
        if cat_dev["items"]:
            results.append(cat_dev)

        # 2. Social Media Caches (WeChat/QQ)
        # 专项扫描 WeChat 和 QQ 的文件接收目录 (File, Video, MsgAttach, Image)
        social_paths = []
        wechat_base = os.path.join(self.home, "Documents", "WeChat Files")
        if os.path.exists(wechat_base):
            for wxid in os.listdir(wechat_base):
                if wxid == "All Users" or wxid == "Applet": continue
                wx_file_storage = os.path.join(wechat_base, wxid, "FileStorage")
                if os.path.exists(wx_file_storage):
                    social_paths.append((f"WeChat 文件 ({wxid})", os.path.join(wx_file_storage, "File")))
                    social_paths.append((f"WeChat 视频 ({wxid})", os.path.join(wx_file_storage, "Video")))
                    social_paths.append((f"WeChat 附件 ({wxid})", os.path.join(wx_file_storage, "MsgAttach")))
                    social_paths.append((f"WeChat 图片 ({wxid})", os.path.join(wx_file_storage, "Image")))
                    
        qq_base = os.path.join(self.home, "Documents", "Tencent Files")
        if os.path.exists(qq_base):
            for qqid in os.listdir(qq_base):
                if not qqid.isdigit(): continue
                social_paths.append((f"QQ 接收文件 ({qqid})", os.path.join(qq_base, qqid, "FileRecv")))
                social_paths.append((f"QQ 图片 ({qqid})", os.path.join(qq_base, qqid, "Image")))
                social_paths.append((f"QQ 视频 ({qqid})", os.path.join(qq_base, qqid, "Video")))

        cat_social = {"category": "社交软件专清 (图片/视频/文件)", "items": []}
        
        for name, base_path in social_paths:
            if not os.path.exists(base_path):
                continue
            if progress_callback: progress_callback(f"正在扫描: {base_path}")
            
            # 扫描指定目录内的文件，保留排除 .db 等安全策略
            for root, _, files in os.walk(base_path):
                for f in files:
                    # 排除微信/QQ数据库及其相关备份、日志文件，防止聊天记录丢失
                    if f.endswith('.db') or f.endswith('.sqlite') or f.endswith('.bakdb') or f.endswith('.db-wal') or f.endswith('.db-shm'):
                        continue
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                        if sz > 10 * 1024 * 1024:  # 社交软件大文件阈值设为 >10MB
                            cat_social["items"].append({
                                "name": f,
                                "path": fp,
                                "size": sz,
                                "type": "file",
                                "checked_by_default": False
                            })
                    except Exception:
                        pass
        if cat_social["items"]:
            results.append(cat_social)

        # 3. Large files in general user dirs (> threshold)
        user_dirs = [
            os.path.join(self.home, "Downloads"),
            os.path.join(self.home, "Documents"),
            os.path.join(self.home, "Videos"),
            os.path.join(self.home, "Desktop")
        ]
        cat_large = {"category": f"用户目录超大文件 (>{self.large_file_threshold_mb}MB)", "items": []}
        
        threshold_bytes = self.large_file_threshold_mb * 1024 * 1024

        for udir in user_dirs:
            if not os.path.exists(udir):
                continue
            if progress_callback: progress_callback(f"正在扫描: {udir}")
            for root, dirs, files in os.walk(udir):
                # 排除刚才扫描过的社交目录和一些隐藏的大型缓存目录，提升遍历速度
                if "WeChat Files" in root or "Tencent Files" in root:
                    # 如果进入了这些目录，清空 dirs 防止继续向下遍历
                    dirs[:] = []
                    continue
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                        if sz > threshold_bytes:
                            cat_large["items"].append({
                                "name": f,
                                "path": fp,
                                "size": sz,
                                "type": "file",
                                "checked_by_default": False
                            })
                    except Exception:
                        pass
        if cat_large["items"]:
            results.append(cat_large)

        if progress_callback: progress_callback("扫描完成")
        return results
