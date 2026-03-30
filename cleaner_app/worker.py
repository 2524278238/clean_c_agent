import os
import shutil
import stat
import datetime
from pathlib import Path
import concurrent.futures
from PyQt6.QtCore import QThread, pyqtSignal
from scanner import Scanner
from registry import RegistryManager

D_DRIVE_BACKUP_DIR = "D:\\C_Drive_Backup"

def force_remove_readonly(func, path, excinfo):
    """
    shutil.rmtree 的回调函数，用于处理只读文件导致的无法删除
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)

class ScanWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)

    def __init__(self, threshold_mb=500):
        super().__init__()
        self.threshold_mb = threshold_mb

    def run(self):
        scanner = Scanner(large_file_threshold_mb=self.threshold_mb)
        results = scanner.scan_all(lambda msg: self.progress.emit(msg))
        self.finished.emit(results)

class CleanWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(int, int) # items_processed, bytes_freed

    def __init__(self, actions):
        super().__init__()
        # actions is a list of dicts: {"path": str, "action": "delete" | "move", "size": int}
        self.actions = actions
        self.registry = RegistryManager()

    def run(self):
        processed = 0
        freed = 0
        
        # 调试信息：打印接收到的任务
        print(f"开始清理任务，共 {len(self.actions)} 个项目")
        
        if not os.path.exists(D_DRIVE_BACKUP_DIR):
            try:
                os.makedirs(D_DRIVE_BACKUP_DIR, exist_ok=True)
            except Exception as e:
                self.progress.emit(f"无法创建D盘备份目录: {str(e)}")
                self.finished.emit(processed, freed)
                return

        for item in self.actions:
            path = item["path"]
            action = item["action"]
            size = item["size"]
            is_dir = item.get("type") == "dir"
            
            if not os.path.exists(path):
                print(f"项目不存在，跳过: {path}")
                continue
                
            try:
                if action == "delete":
                    self.progress.emit(f"正在删除: {path}")
                    if is_dir:
                        # 对于目录，我们尝试删除里面的内容
                        freed_in_dir = 0
                        try:
                            for f_name in os.listdir(path):
                                f_path = os.path.join(path, f_name)
                                try:
                                    f_size = 0
                                    if os.path.isfile(f_path) or os.path.islink(f_path):
                                        f_size = os.path.getsize(f_path)
                                        # 尝试解除只读
                                        os.chmod(f_path, stat.S_IWRITE)
                                        os.remove(f_path)
                                        freed_in_dir += f_size
                                    elif os.path.isdir(f_path):
                                        # 递归计算目录大小
                                        from scanner import get_size
                                        f_size = get_size(f_path)
                                        shutil.rmtree(f_path, onerror=force_remove_readonly)
                                        freed_in_dir += f_size
                                except Exception:
                                    pass # 忽略被占用无法删除的文件
                        except Exception as e:
                            print(f"读取目录失败 {path}: {e}")
                        
                        processed += 1
                        freed += freed_in_dir
                    else:
                        # 对于单个文件
                        try:
                            # 尝试解除只读
                            os.chmod(path, stat.S_IWRITE)
                            if os.path.isfile(path) or os.path.islink(path):
                                os.remove(path)
                            elif os.path.isdir(path):
                                shutil.rmtree(path, onerror=force_remove_readonly)
                            processed += 1
                            freed += size
                        except Exception as e:
                            self.progress.emit(f"删除失败 (可能被占用): {os.path.basename(path)}")
                            print(f"删除失败 {path}: {e}")
                            
                elif action == "move":
                    self.progress.emit(f"正在移动: {path}")
                    try:
                        if is_dir:
                            # 对于目录，在 D 盘创建对应文件夹，将内容移动过去
                            base_name = os.path.basename(path)
                            dest_dir = os.path.join(D_DRIVE_BACKUP_DIR, f"{item.get('id', 'item')}_{base_name}")
                            os.makedirs(dest_dir, exist_ok=True)
                            
                            moved_size = 0
                            for f_name in os.listdir(path):
                                f_path = os.path.join(path, f_name)
                                try:
                                    from scanner import get_size
                                    f_size = get_size(f_path)
                                    shutil.move(f_path, os.path.join(dest_dir, f_name))
                                    moved_size += f_size
                                except Exception:
                                    pass
                            self.registry.add_entry(path, dest_dir, moved_size)
                            processed += 1
                            freed += moved_size
                        else:
                            # 单个文件移动
                            base_name = os.path.basename(path)
                            dest_path = os.path.join(D_DRIVE_BACKUP_DIR, f"{item.get('id', 'item')}_{base_name}")
                            shutil.move(path, dest_path)
                            self.registry.add_entry(path, dest_path, size)
                            processed += 1
                            freed += size
                    except Exception as e:
                        self.progress.emit(f"移动失败: {os.path.basename(path)}")
                        print(f"移动失败 {path}: {e}")
            except Exception as e:
                self.progress.emit(f"项目处理异常: {os.path.basename(path)}")
                print(f"处理异常 {path}: {e}")
                
        self.finished.emit(processed, freed)

class RestoreWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(int) # items_restored

    def __init__(self, entries_to_restore):
        super().__init__()
        # list of dicts from registry
        self.entries = entries_to_restore
        self.registry = RegistryManager()

    def run(self):
        restored = 0
        for entry in self.entries:
            d_path = entry["d_drive_path"]
            orig_path = entry["original_path"]
            
            self.progress.emit(f"正在还原: {orig_path}")
            try:
                if os.path.exists(d_path):
                    orig_dir = os.path.dirname(orig_path)
                    if not os.path.exists(orig_dir):
                        os.makedirs(orig_dir, exist_ok=True)
                        
                    shutil.move(d_path, orig_path)
                    self.registry.remove_entry(entry["id"])
                    restored += 1
                else:
                    self.progress.emit(f"找不到备份文件: {d_path}")
            except Exception as e:
                self.progress.emit(f"还原失败 {orig_path}: {str(e)}")
                
        self.finished.emit(restored)

class DirectoryAnalysisWorker(QThread):
    finished = pyqtSignal(list, dict)

    def __init__(self, target_dir, global_dir_cache=None, force_rescan=False):
        super().__init__()
        self.target_dir = target_dir
        self.global_dir_cache = global_dir_cache if global_dir_cache is not None else {}
        self.new_dir_cache = {}
        self.force_rescan = force_rescan

    def run(self):
        results = []
        try:
            items_to_process = []
            for item in os.listdir(self.target_dir):
                item_path = os.path.join(self.target_dir, item)
                if os.path.islink(item_path):
                    continue # 跳过符号链接
                
                is_dir = os.path.isdir(item_path)
                items_to_process.append((item, item_path, is_dir))

            # 使用线程池并发计算各个子目录的大小
            with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
                # 提交所有任务
                future_to_item = {}
                for item, item_path, is_dir in items_to_process:
                    try:
                        st = os.stat(item_path)
                        mtime_str = datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        mtime_str = "未知"

                    if is_dir:
                        if not self.force_rescan and item_path in self.global_dir_cache:
                            # 非强制扫描且命中缓存，直接使用（兼容老版本 int 和新版本 dict 缓存）
                            val = self.global_dir_cache[item_path]
                            size = val["size"] if isinstance(val, dict) else val
                            results.append((item, item_path, size, is_dir, mtime_str))
                        else:
                            future = executor.submit(self.get_dir_size, item_path, self.new_dir_cache)
                            future_to_item[future] = (item, item_path, is_dir, mtime_str)
                    else:
                        try:
                            size = os.path.getsize(item_path)
                        except Exception:
                            size = 0
                        results.append((item, item_path, size, is_dir, mtime_str))
                
                # 收集并发计算的结果
                for future in concurrent.futures.as_completed(future_to_item):
                    item, item_path, is_dir, mtime_str = future_to_item[future]
                    try:
                        size = future.result()
                    except Exception:
                        size = 0
                    results.append((item, item_path, size, is_dir, mtime_str))

            # 按大小降序排列
            results.sort(key=lambda x: x[2], reverse=True)
        except Exception as e:
            print(f"分析线程运行出错: {e}")
            
        self.finished.emit(results, self.new_dir_cache)

    def get_dir_size(self, path, cache_dict):
        # 1. 先尝试从全局缓存中获取该目录的旧信息
        cached_val = self.global_dir_cache.get(path)
        
        # 获取当前目录的状态
        try:
            st = os.stat(path)
            current_mtime = st.st_mtime
        except Exception:
            return 0

        # 【智能跳过策略】：
        # 如果不是顶级目录（顶级目录必须扫描以更新结果列表），
        # 且缓存中存在该目录，且其 mtime 未变，
        # 则可以直接返回缓存值，不需要再递归进入其数以万计的子目录。
        if path != self.target_dir and cached_val and isinstance(cached_val, dict):
            if cached_val.get("mtime") == current_mtime:
                # 注意：这里我们依然要把这个缓存项复制到新的 cache_dict 中，以便持久化
                cache_dict[path] = cached_val
                return cached_val["size"]

        total = 0
        try:
            # os.scandir 在 Windows 上非常快，因为它会顺便返回文件的 size 和 mtime
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        # 跳过符号链接，避免死循环或重复计算
                        if entry.is_symlink():
                            continue
                            
                        if entry.is_file(follow_symlinks=False):
                            # 直接从 DirEntry 获取大小（Windows 下无需额外系统调用）
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            # 递归计算子目录，每一层都会触发上面的 mtime 校验
                            sub_total = self.get_dir_size(entry.path, cache_dict)
                            total += sub_total
                    except Exception:
                        pass
        except Exception:
            pass
            
        # 记录/更新当前目录的缓存
        new_cache_entry = {"size": total, "mtime": current_mtime}
        cache_dict[path] = new_cache_entry
        return total
