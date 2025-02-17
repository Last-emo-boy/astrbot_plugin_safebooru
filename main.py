import os
import json
import difflib
import tempfile
import aiohttp
import openpyxl

from astrbot.api.all import *

@register("safebooru", "w33d", "从 safebooru 获取图片的插件", "1.0.0", "https://github.com/Last-emo-boy/astrbot_plugin_safebooru")
class SafebooruPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        if config is None:
            config = {}
        super().__init__(context)
        self.config = config
        self.limit = self.config.get("limit", 100)  # 默认 limit 值为 100
        self.tag_mapping = self.load_tag_mapping("tag_mapping.xlsx")
        self.usage_file = "usage_count.json"
        self.usage_counts = self.load_usage_counts()


    def load_tag_mapping(self, filepath: str) -> dict:
        """
        从 xlsx 文件中加载标签映射
        期望第一列为真实 tag，第二列为中文描述（right_tag_cn）。
        返回一个字典，键为中文标签，值为真实 tag。
        """
        mapping = {}
        if os.path.exists(filepath):
            wb = openpyxl.load_workbook(filepath)
            sheet = wb.active
            for row in sheet.iter_rows(values_only=True):
                # 忽略空行，确保两列都有值
                if row[0] and row[1]:
                    mapping[str(row[1])] = str(row[0])
            wb.close()
        return mapping

    def load_usage_counts(self) -> dict:
        """
        从持久化记录文件中加载每个 tag 的使用次数，
        若文件不存在则返回空字典。
        """
        if os.path.exists(self.usage_file):
            try:
                with open(self.usage_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        else:
            return {}

    def save_usage_counts(self):
        """
        将使用次数写入持久化文件。
        """
        try:
            with open(self.usage_file, "w", encoding="utf-8") as f:
                json.dump(self.usage_counts, f)
        except Exception as e:
            print("保存使用次数出错：", e)

    @command("safebooru")
    async def fetch_image(self, event: AstrMessageEvent, tag: str):
        """
        根据用户输入的标签（允许中文）从 safebooru 获取图片。
        
        参数:
            tag(string): 用户输入的图片标签（可能为中文）
        
        流程：
        1. 使用 difflib 在加载的标签映射中找到最相似的中文标签，
           得到对应真实的查询 tag。
        2. 根据配置的 limit 构造 API 请求，获取 JSON 格式的图片列表。
        3. 根据该 tag 的使用次数（持久化记录）选取图片，并更新计数。
        4. 下载图片后发送给用户，再删除本地缓存文件。
        """
        if not self.tag_mapping:
            yield event.plain_result("未加载标签映射文件，请检查 tag_mapping.xlsx 是否存在。")
            return

        # 使用模糊匹配寻找最相似的中文标签
        candidates = list(self.tag_mapping.keys())
        matches = difflib.get_close_matches(tag, candidates, n=1, cutoff=0.1)
        if matches:
            best_match = matches[0]
            query_tag = self.tag_mapping[best_match]
        else:
            yield event.plain_result("未找到匹配的标签。")
            return

        # 获取该 tag 的使用次数，决定返回图片的索引
        count = self.usage_counts.get(query_tag, 0)

        # 构造 API 请求 URL
        api_url = (f"https://safebooru.org/index.php?page=dapi&s=post&q=index"
                   f"&tags={query_tag}&limit={self.limit}&json=1")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as resp:
                    if resp.status != 200:
                        yield event.plain_result("无法获取图片数据，请稍后重试。")
                        return
                    posts = await resp.json(content_type=None)
        except Exception as e:
            yield event.plain_result(f"获取图片数据时出错: {e}")
            return

        if not posts:
            yield event.plain_result("未找到相关图片。")
            return

        # 选取使用次数对应的图片（循环使用）
        index = count % len(posts)
        post = posts[index]
        file_url = post.get("file_url")
        if not file_url:
            yield event.plain_result("未获取到图片链接。")
            return

        # 下载图片到临时文件
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as img_resp:
                    if img_resp.status != 200:
                        yield event.plain_result("下载图片失败。")
                        return
                    img_data = await img_resp.read()
                    temp_dir = tempfile.gettempdir()
                    temp_file_path = os.path.join(temp_dir, os.path.basename(file_url))
                    with open(temp_file_path, "wb") as f:
                        f.write(img_data)
        except Exception as e:
            yield event.plain_result(f"下载图片时出错: {e}")
            return

        # 更新该 tag 的使用次数，并持久化保存
        self.usage_counts[query_tag] = count + 1
        self.save_usage_counts()

        # 发送图片给用户
        yield event.image_result(temp_file_path)

        # 删除临时文件
        try:
            os.remove(temp_file_path)
        except Exception as e:
            print("删除临时文件失败：", e)
