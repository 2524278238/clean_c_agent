import os
import json
import datetime
from openai import OpenAI
from dotenv import load_dotenv

SETTINGS_FILE = "settings.json"

class AIEngine:
    def __init__(self):
        self.settings = self.load_settings()
        self.client = None
        self.chat_history = []
        self._init_client()
        self._reset_history()

    def _reset_history(self):
        self.chat_history = [
            {"role": "system", "content": "你是一个专业的 Windows 磁盘分析助手和空间清理专家。你可以使用提供的工具（如 list_directory）来获取系统目录的具体信息，以帮助用户进行判断。"}
        ]
        
    def get_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "获取指定文件夹下的文件和子目录列表，包含大小和修改时间。用于分析特定文件夹的内部内容。必须传入完整的绝对路径。如果用户提供的是相对路径或只是文件夹名称，请结合系统提示中给出的当前分析目录路径，拼接出完整的绝对路径再调用此工具。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "要查看的文件夹的完整绝对路径，例如 C:\\Users\\lyt\\AppData。请不要使用相对路径。"
                            }
                        },
                        "required": ["path"]
                    }
                }
            }
        ]

    def execute_list_directory(self, path):
        if not os.path.exists(path):
            return f"路径不存在: {path}"
        if not os.path.isdir(path):
            return f"不是一个文件夹: {path}"
            
        try:
            items = []
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        stat = entry.stat(follow_symlinks=False)
                        size = stat.st_size if entry.is_file(follow_symlinks=False) else 0
                        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        item_type = "文件夹" if entry.is_dir(follow_symlinks=False) else "文件"
                        items.append(f"- {entry.name} ({item_type}, 大小: {size} 字节, 修改时间: {mtime})")
                    except Exception as inner_e:
                        # 即使获取属性失败，也应该把名字列出来，否则会被当成不存在
                        item_type = "未知"
                        try:
                            item_type = "文件夹" if entry.is_dir(follow_symlinks=False) else "文件"
                        except:
                            pass
                        items.append(f"- {entry.name} ({item_type}, 大小: 未知, 修改时间: 未知)")
                        print(f"[AI Tool Call] 无法获取文件属性 {entry.name}: {inner_e}")
            
            if not items:
                return "文件夹为空。"
                
            if len(items) > 50:
                return "\n".join(items[:50]) + f"\n... (还有 {len(items)-50} 个项目未显示)"
            return "\n".join(items)
        except Exception as e:
            return f"无法读取目录: {str(e)}"

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        
        # 默认设置，尝试从 .env 读取
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
        env_key = os.getenv("deepseek_api_key", "")
        
        return {
            "provider": "DeepSeek",
            "api_key": env_key,
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat"
        }

    def save_settings(self, settings):
        self.settings = settings
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
        self._init_client()

    def _init_client(self):
        if self.settings.get("api_key"):
            self.client = OpenAI(
                api_key=self.settings["api_key"],
                base_url=self.settings.get("base_url", "https://api.deepseek.com")
            )
        else:
            self.client = None

    def analyze_folders(self, folder_info_list):
        """
        分析大文件夹的作用
        folder_info_list: [{"name": str, "path": str, "size": str, "mtime": str}, ...]
        """
        if not self.client:
            return "请先在设置中配置 API Key。"

        prompt = "你是一个 Windows 系统空间清理专家。请根据以下文件夹信息（名称、路径、大小、最后修改时间），分析这些文件夹的作用，并给出是否建议删除或清理的建议。注意识别常见的软件目录、系统目录和用户数据目录。\n\n"
        for info in folder_info_list:
            prompt += f"- 文件夹: {info['name']}\n  路径: {info['path']}\n  大小: {info['size']}\n  最后修改时间: {info['mtime']}\n\n"
        
        prompt += """
请以 Markdown 表格的形式回答，包含以下列：
1. **文件夹名称**
2. **作用分析** (详细说明该目录存放的是什么，属于哪个软件或系统组件)
3. **清理建议** (建议删除、建议保留、或者如何安全清理)
4. **风险等级** (低/中/高)

最后请给出一个总体的清理策略。"""

        try:
            response = self.client.chat.completions.create(
                model=self.settings.get("model", "deepseek-chat"),
                messages=[
                    {"role": "system", "content": "你是一个专业的 Windows 磁盘分析助手，擅长以清晰的 Markdown 表格形式提供分析。"},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"AI 分析出错: {str(e)}"

    def chat(self, message, current_path=None):
        """
        与用户进行对话，支持上下文记忆和工具调用
        """
        if not self.client:
            return "请先在设置中配置 API Key。"

        # 如果提供了当前路径，就在消息中附加这个上下文，但不显示给用户
        if current_path:
            context_msg = f"[系统信息: 用户当前在软件界面中正在分析的目录路径是 {current_path}]\n\n{message}"
        else:
            context_msg = message

        self.chat_history.append({"role": "user", "content": context_msg})

        # 限制历史记录长度，保留 system prompt，加上最近的 20 条消息 (10轮对话)
        if len(self.chat_history) > 21:
            self.chat_history = [self.chat_history[0]] + self.chat_history[-20:]

        try:
            response = self.client.chat.completions.create(
                model=self.settings.get("model", "deepseek-chat"),
                messages=self.chat_history,
                tools=self.get_tools()
            )
            
            response_message = response.choices[0].message
            
            # 将助手的回复存入历史
            msg_dict = {"role": response_message.role, "content": response_message.content or ""}
            if response_message.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": t.id, 
                        "type": t.type, 
                        "function": {"name": t.function.name, "arguments": t.function.arguments}
                    } for t in response_message.tool_calls
                ]
            self.chat_history.append(msg_dict)

            # 检查是否调用了工具
            if response_message.tool_calls:
                for tool_call in response_message.tool_calls:
                    if tool_call.function.name == "list_directory":
                        import json
                        try:
                            args = json.loads(tool_call.function.arguments)
                            path = args.get("path")
                            print(f"\n[AI Tool Call] 调用工具: list_directory, 参数 path: {path}")
                            tool_result = self.execute_list_directory(path)
                            print(f"[AI Tool Call] 工具执行结果长度: {len(tool_result)} 字符")
                            # 只打印前100个字符作为截断日志，避免刷屏
                            preview_result = tool_result[:100].replace('\n', ' ') + ('...' if len(tool_result) > 100 else '')
                            print(f"[AI Tool Call] 结果预览: {preview_result}\n")
                        except Exception as e:
                            tool_result = f"工具执行出错: {str(e)}"
                            print(f"\n[AI Tool Call] 执行异常: {tool_result}\n")
                        
                        self.chat_history.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": tool_result
                        })
                
                # 带着工具的返回结果再次请求大模型
                second_response = self.client.chat.completions.create(
                    model=self.settings.get("model", "deepseek-chat"),
                    messages=self.chat_history
                )
                final_message = second_response.choices[0].message
                self.chat_history.append({"role": final_message.role, "content": final_message.content or ""})
                return final_message.content

            return response_message.content
        except Exception as e:
            return f"AI 对话出错: {str(e)}"
