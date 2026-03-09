import re
import json
import html
from pathlib import Path

import aiohttp
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    )
}


@register("douyin_parser", "小晨(Rainy-C)", "解析抖音分享链接并发送无水印视频", "1.0.0", "https://github.com/Rainy-C/astrbot_plugin_douyin_parser")
class DouyinParser(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.data_dir = Path("data") / "douyin_parser"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @filter.command("douyin")
    async def douyin(self, event: AstrMessageEvent, share_text: str):
        """解析抖音分享文本并发送无水印视频
        用法：/douyin <抖音分享文本或链接>
        """
        try:
            info = await self._parse_share_text(share_text)
            title = info["title"]
            video_url = info["url"]
            video_id = info["video_id"]

            yield event.plain_result(f"标题：{title}")

            video_path = self.data_dir / f"{video_id}.mp4"
            await self._download_file(video_url, video_path)

            video = Comp.Video.fromFileSystem(path=str(video_path))
            yield event.chain_result([video])

        except Exception as e:
            logger.error(f"douyin parse error: {e}", exc_info=True)
            yield event.plain_result(f"解析失败：{e}")
        finally:
            try:
                if "video_path" in locals() and video_path.exists():
                    video_path.unlink()
            except Exception:
                pass

    async def _parse_share_text(self, share_text: str) -> dict:
        # 处理不可见字符 + HTML 实体
        cleaned = html.unescape(share_text).strip()

        # 更宽松的链接匹配（只要 http(s) 开头，直到空白结束）
        urls = re.findall(r"https?://\S+", cleaned)
        if not urls:
            raise ValueError("未找到有效的分享链接")

        share_url = urls[0]

        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(share_url, allow_redirects=True) as resp:
                final_url = str(resp.url)

            video_id = final_url.split("?")[0].strip("/").split("/")[-1]
            share_url = f"https://www.iesdouyin.com/share/video/{video_id}"

            async with session.get(share_url) as resp:
                html_text = await resp.text()

        pattern = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", re.DOTALL)
        match = pattern.search(html_text)
        if not match:
            raise ValueError("无法解析视频信息（HTML 无 ROUTER_DATA）")

        json_data = json.loads(match.group(1).strip())

        video_key = "video_(id)/page"
        note_key = "note_(id)/page"

        if video_key in json_data["loaderData"]:
            data = json_data["loaderData"][video_key]["videoInfoRes"]["item_list"][0]
        elif note_key in json_data["loaderData"]:
            data = json_data["loaderData"][note_key]["videoInfoRes"]["item_list"][0]
        else:
            raise ValueError("无法解析视频或图集信息")

        video_url = data["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
        title = data.get("desc", "").strip() or f"douyin_{video_id}"
        title = re.sub(r'[\\/:*?"<>|]', "_", title)

        return {"url": video_url, "title": title, "video_id": video_id}

    async def _download_file(self, url: str, save_path: Path):
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                with open(save_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)

    async def terminate(self):
        try:
            for p in self.data_dir.glob("*.mp4"):
                p.unlink()
        except Exception:
            pass
