from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
import random
import oss2
import requests
import os

@register("setu", "YourName", "随机OSS图片插件（按文件夹随机）", "1.0.0", "https://github.com/yourrepo/astrbot_plugin_setu")
class SetuPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        # 初始化 OSS 连接，相关配置请在 _conf_schema.json 中配置
        auth = oss2.Auth(config['oss_access_key_id'], config['oss_access_key_secret'])
        # 如果你的 OSS SDK 使用v4签名且需要region，可以在配置中添加region参数，此处示例不使用region参数
        self.bucket = oss2.Bucket(auth, config['oss_endpoint'], config['bucket_name'])

    def get_random_object_from_random_prefix(self):
        """
        先随机选择一个一级目录（文件夹），再在该目录中使用水塘抽样随机选取一个对象。
        如果存在文件夹但选中的文件夹为空，则退回到整体遍历；若没有文件夹，则直接遍历整个桶。
        """
        prefixes = []
        # 列出所有一级目录，delimiter='/' 表示按斜杠分割
        for obj in oss2.ObjectIterator(self.bucket, delimiter='/'):
            if obj.is_prefix():
                prefixes.append(obj.prefix)
        if prefixes:
            # 随机选取一个目录
            random_prefix = random.choice(prefixes)
            random_obj = None
            count = 0
            for obj in oss2.ObjectIterator(self.bucket, prefix=random_prefix):
                count += 1
                if random.randint(1, count) == 1:
                    random_obj = obj
            if random_obj:
                return random_obj
            else:
                # 选定的目录内没有文件，则退回到遍历整个桶
                return self.get_random_object_overall()
        else:
            # 如果没有文件夹，则直接遍历整个桶
            return self.get_random_object_overall()

    def get_random_object_overall(self):
        """
        遍历整个桶，使用水塘抽样随机选取一个对象
        """
        random_obj = None
        count = 0
        for obj in oss2.ObjectIterator(self.bucket):
            count += 1
            if random.randint(1, count) == 1:
                random_obj = obj
        return random_obj

    @filter.command("setu")
    async def setu(self, event: AstrMessageEvent):
        """
        处理 /setu 指令：从 OSS 中随机获取图片（跨文件夹随机），下载后发送到群聊
        """
        try:
            random_object = self.get_random_object_from_random_prefix()
            if not random_object:
                yield event.plain_result("OSS中没有找到文件！")
                return
            
            object_key = random_object.key

            # 根据配置中的内网 URL 前缀构造图片链接
            internal_url_prefix = self.config.get('internal_url_prefix', '')
            image_url = internal_url_prefix.rstrip('/') + '/' + object_key

            # 确定临时下载目录（例如 /tmp），检查目录是否存在，不存在则创建
            temp_dir = "/tmp"
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            temp_filename = os.path.join(temp_dir, os.path.basename(object_key))

            # 使用 requests 下载图片，模拟OSS下载示例中对本地文件的保存方式
            response = requests.get(image_url)
            if response.status_code == 200:
                with open(temp_filename, "wb") as f:
                    f.write(response.content)
                # 下载完成后打印提示（或用于日志记录）
                print("Download complete: ", temp_filename)
                # 发送图片消息到群聊
                yield event.image_result(temp_filename)
                # 删除临时文件，避免占用磁盘空间
                os.remove(temp_filename)
            else:
                yield event.plain_result("图片下载失败，状态码: " + str(response.status_code))
        except Exception as e:
            yield event.plain_result("发生错误: " + str(e))
