"""
抖音视频信息抓取服务 - 四通道多轨串联方案
通道 1: 自建 HTTP 解析（httpx 跟随重定向 + aweme_id 提取）
通道 2: Playwright 无头浏览器（兜底，最稳但最慢）
通道 3: TikHub API（按序备选，有 Key 时加速）
通道 4: ixigua.com 西瓜视频（字节系风控弱，备用）
"""
import os
import re
import time
import asyncio
import httpx
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# TikHub API 配置
TIKHUB_API_KEY = os.getenv("TIKHUB_API_KEY", "")
TIKHUB_API_BASE = "https://api.tikhub.io/api/v1"


# ============== 统一结果类型 ==============

class VideoMeta:
    """解析成功后的元数据结构，所有通道返回统一格式"""
    def __init__(self,
                 title: str = "",
                 author: str = "",
                 duration: str = "",
                 likes: int = 0,
                 comments: int = 0,
                 shares: int = 0,
                 cover_url: str = "",
                 video_url: str = "",
                 audio_url: str = "",
                 is_mock: bool = False,
                 source_channel: str = ""):
        self.title = title
        self.author = author
        self.duration = duration
        self.likes = likes
        self.comments = comments
        self.shares = shares
        self.cover_url = cover_url
        self.video_url = video_url
        self.audio_url = audio_url
        self.is_mock = is_mock
        self.source_channel = source_channel

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "duration": self.duration,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "cover_url": self.cover_url,
            "video_url": self.video_url,
            "audio_url": self.audio_url,
            "is_mock": self.is_mock,
            "source_channel": self.source_channel,
        }

    @staticmethod
    def mock(url: str = "") -> "VideoMeta":
        return VideoMeta(
            title="【示例】如何养成好习惯 - 读书分享",
            author="读书分享家",
            duration="05:20",
            likes=85000,
            comments=1200,
            shares=3400,
            cover_url="",
            video_url="",
            is_mock=True,
            source_channel="mock",
        )


# ============== 主入口 ==============

async def fetch_douyin_video_info(share_text: str) -> dict:
    """
    入口函数：四通道按序串联，任一通道成功立即返回，全部失败返回 Mock。
    调用方无需感知内部细节。
    """
    resolver = VideoResolver(share_text)
    meta = await resolver.resolve()
    return meta.to_dict()


# ============== 主解析器 ==============

class VideoResolver:
    """
    四通道串联解析器。

    通道 1 - 自建 HTTP（httpx）：最快，自建可控
    通道 2 - Playwright：无头浏览器，最稳兜底
    通道 3 - TikHub API：有 Key 时加速返回
    通道 4 - ixigua 西瓜视频：字节系风控弱
    """

    def __init__(self, share_text: str):
        self.share_text = share_text
        self.short_url: Optional[str] = None   # 提取出的 v.douyin.com 短链
        self.full_url: Optional[str] = None     # 重定向后的完整 URL
        self.aweme_id: Optional[str] = None     # 视频唯一 ID

    async def resolve(self) -> VideoMeta:
        """
        按通道顺序尝试解析，全部失败则返回 Mock。
        每一步失败都记录原因并自动切换下一通道。
        """
        # 前置：从分享文本提取短链（所有通道共用）
        self.short_url = extract_douyin_url(self.share_text)
        if not self.short_url:
            print(f"[douyin] 无法从文本提取抖音短链: {self.share_text[:50]}...")
            return VideoMeta.mock()

        print(f"[douyin] 提取到短链: {self.short_url}")

        # ---- 通道 1: 自建 HTTP ----
        meta = await self._try_channel1()
        if meta:
            return meta

        # ---- 通道 2: Playwright ----
        meta = await self._try_channel2()
        if meta:
            return meta

        # ---- 通道 3: TikHub API ----
        meta = await self._try_channel3()
        if meta:
            return meta

        # ---- 通道 4: ixigua 西瓜视频 ----
        meta = await self._try_channel4()
        if meta:
            return meta

        # 全部失败
        print(f"[douyin] 所有通道均失败，返回 Mock")
        return VideoMeta.mock(self.short_url)

    # ==================== 通道 1: 自建 HTTP ====================

    async def _try_channel1(self) -> Optional[VideoMeta]:
        """
        通道 1：自建 HTTP 解析
        步骤：跟随重定向 → 提取 aweme_id → 自建请求获取元数据
        不依赖任何第三方 API，完全自控。
        """
        print(f"[通道1] 开始自建 HTTP 解析...")

        for attempt in range(1, 4):  # 指数退避重试
            try:
                # Step 1: 跟随重定向，提取 aweme_id
                self.aweme_id = await _resolve_aweme_id_http(self.short_url, attempt)
                if not self.aweme_id:
                    if attempt < 3:
                        wait = 2 ** attempt
                        print(f"[通道1] aweme_id 提取失败，{wait}s 后重试 ({attempt}/3)...")
                        await asyncio.sleep(wait)
                        continue
                    else:
                        print(f"[通道1] aweme_id 提取失败，切换通道2")
                        return None

                print(f"[通道1] 提取到 aweme_id: {self.aweme_id}")

                # Step 2: 用 aweme_id 构造抖音移动端 API 请求（自建，不依赖 TikHub）
                meta = await _fetch_video_meta_selfhosted(self.aweme_id, attempt)
                if meta:
                    meta.source_channel = "channel1_http"
                    print(f"[通道1] 成功，来源: channel1_http")
                    return meta

            except Exception as e:
                print(f"[通道1] 第 {attempt} 次异常: {type(e).__name__}: {str(e)}")
                if attempt == 3:
                    print(f"[通道1] 重试耗尽，切换通道2")

            if attempt < 3:
                wait = 2 ** attempt
                await asyncio.sleep(wait)

        return None

    # ==================== 通道 2: Playwright ====================

    async def _try_channel2(self) -> Optional[VideoMeta]:
        """
        通道 2：Playwright 无头浏览器
        用真实浏览器打开页面，最慢但最稳。
        抖音 PC/移动端页面都能解析。
        """
        print(f"[通道2] 启动 Playwright 无头浏览器...")

        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        except ImportError:
            print(f"[通道2] Playwright 未安装，跳过")
            return None

        for attempt in range(1, 3):
            try:
                meta = await asyncio.get_event_loop().run_in_executor(
                    None, _playwright_fetch, self.short_url, self.aweme_id, attempt
                )
                if meta:
                    meta.source_channel = "channel2_playwright"
                    print(f"[通道2] 成功，来源: channel2_playwright")
                    return meta
            except Exception as e:
                print(f"[通道2] 第 {attempt} 次异常: {type(e).__name__}: {str(e)}")
                if attempt < 2:
                    wait = 5
                    print(f"[通道2] {wait}s 后重试...")
                    await asyncio.sleep(wait)

        print(f"[通道2] Playwright 解析失败，切换通道3")
        return None

    # ==================== 通道 3: TikHub API ====================

    async def _try_channel3(self) -> Optional[VideoMeta]:
        """
        通道 3：TikHub API
        已有 aweme_id 时直接调用；没有则先解析。
        按次付费，有 Key 时速度最快。
        """
        if not TIKHUB_API_KEY:
            print(f"[通道3] TIKHUB_API_KEY 未配置，跳过")
            return None

        print(f"[通道3] 调用 TikHub API...")

        for attempt in range(1, 4):
            try:
                # 如果还没有 aweme_id，先从短链提取
                if not self.aweme_id:
                    self.aweme_id = await _resolve_aweme_id_http(self.short_url, attempt)
                    if not self.aweme_id and attempt < 3:
                        wait = 2 ** attempt
                        print(f"[通道3] aweme_id 提取失败，{wait}s 后重试...")
                        await asyncio.sleep(wait)
                        continue

                if not self.aweme_id:
                    continue

                meta = await _fetch_via_tikhub(self.aweme_id)
                if meta:
                    meta.source_channel = "channel3_tikhub"
                    print(f"[通道3] 成功，来源: channel3_tikhub")
                    return meta

            except Exception as e:
                print(f"[通道3] 第 {attempt} 次异常: {type(e).__name__}: {str(e)}")

            if attempt < 3:
                wait = 2 ** attempt
                await asyncio.sleep(wait)

        print(f"[通道3] TikHub 解析失败，切换通道4")
        return None

    # ==================== 通道 4: ixigua 西瓜视频 ====================

    async def _try_channel4(self) -> Optional[VideoMeta]:
        """
        通道 4：ixigua.com 西瓜视频解析
        字节系产品，风控比抖音弱很多。
        将抖音 aweme_id 映射到 ixigua 播放页进行解析。
        """
        print(f"[通道4] 尝试 ixigua 西瓜视频解析...")

        if not self.aweme_id:
            print(f"[通道4] 无 aweme_id，无法构造 ixigua 链接")
            return None

        for attempt in range(1, 3):
            try:
                meta = await _fetch_ixigua(self.aweme_id, attempt)
                if meta:
                    meta.source_channel = "channel4_ixigua"
                    print(f"[通道4] 成功，来源: channel4_ixigua")
                    return meta
            except Exception as e:
                print(f"[通道4] 第 {attempt} 次异常: {type(e).__name__}: {str(e)}")

            if attempt < 2:
                await asyncio.sleep(3)

        print(f"[通道4] ixigua 解析失败，返回 Mock")
        return None


# ============== 短链 URL 提取（所有通道共用）==============

def extract_douyin_url(text: str) -> Optional[str]:
    """从分享文本中正则提取抖音真实 URL"""
    patterns = [
        r'https?://v\.douyin\.com/[a-zA-Z0-9_-]+',
        r'v\.douyin\.com/[a-zA-Z0-9_-]+',
        r'https?://www\.douyin\.com/video/\d+',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            url = match.group(0)
            if not url.startswith('http'):
                url = 'https://' + url
            return url
    return None


# ============== 通道 1 子函数 ==============

async def _resolve_aweme_id_http(url: str, attempt: int = 1) -> Optional[str]:
    """
    自建 HTTP 解析：用 httpx 跟随重定向，从最终 URL 提取 aweme_id。
    每次重试更换 User-Agent，降低被识别概率。
    """
    user_agents = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    ]
    ua = user_agents[(attempt - 1) % len(user_agents)]

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": ua}
        ) as client:
            response = await client.get(url)
            final_url = str(response.url)
            aweme_match = re.search(r'/video/(\d+)', final_url)
            if aweme_match:
                print(f"[通道1] 重定向完成，aweme_id={aweme_match.group(1)}")
                return aweme_match.group(1)
            print(f"[通道1] 无法从 URL 提取 aweme_id: {final_url}")
    except httpx.TimeoutException:
        print(f"[通道1] 请求超时")
    except Exception as e:
        print(f"[通道1] HTTP 错误: {type(e).__name__}: {str(e)}")
    return None


async def _fetch_video_meta_selfhosted(aweme_id: str, attempt: int = 1) -> Optional[VideoMeta]:
    """
    自建抖音移动端 API 请求（不依赖 TikHub）。
    抖音移动端接口: https://www.iesdouyin.com/share/video/{aweme_id}/
    真实请求会返回包含 og:title、og:image 等 Open Graph 元数据的 HTML，
    可直接正则提取标题、封面。
    """
    user_agents = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    ]

    urls_to_try = [
        f"https://www.iesdouyin.com/share/video/{aweme_id}/",
        f"https://www.douyin.com/video/{aweme_id}",
    ]

    for url in urls_to_try:
        for at in range(1, 3):
            ua = user_agents[(at - 1) % len(user_agents)]
            try:
                async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": ua}) as client:
                    resp = await client.get(url, follow_redirects=True)

                    if resp.status_code != 200:
                        continue

                    html = resp.text

                    # 提取标题（Open Graph og:title）
                    title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
                    title = title_match.group(1) if title_match else ""

                    # 提取描述
                    desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
                    desc = desc_match.group(1) if desc_match else ""

                    # 提取封面图
                    cover_match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                    cover_url = cover_match.group(1) if cover_match else ""

                    # 提取作者昵称（rendition 相关）
                    author_match = re.search(r'"author":"([^"]+)"', html)
                    author = author_match.group(1) if author_match else ""

                    if title or desc or cover_url:
                        video_url = f"https://www.douyin.com/video/{aweme_id}"
                        return VideoMeta(
                            title=title or desc or "未知标题",
                            author=author or "未知作者",
                            duration="",
                            likes=0,
                            comments=0,
                            shares=0,
                            cover_url=cover_url,
                            video_url=video_url,
                        )

            except Exception as e:
                print(f"[通道1] 自建请求失败 ({url}): {type(e).__name__}: {str(e)}")
                await asyncio.sleep(1)

    return None


# ============== 通道 2 子函数：Playwright ==============

def _playwright_fetch(short_url: str, aweme_id: Optional[str], attempt: int) -> Optional[VideoMeta]:
    """
    Playwright 无头浏览器抓取。
    在线程池中同步运行（避免阻塞事件循环）。
    支持抖音移动端和 PC 端。
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    urls_to_try = []
    if short_url:
        urls_to_try.append(short_url)
    if aweme_id:
        urls_to_try.extend([
            f"https://www.douyin.com/video/{aweme_id}",
            f"https://v.douyin.com/{aweme_id}",
        ])

    for url in urls_to_try:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                    viewport={"width": 390, "height": 844},
                    locale="zh-CN",
                )
                page = context.new_page()

                # 拦截网络请求，只获取关键数据后立即关闭
                page.goto(url, timeout=30000, wait_until="domcontentloaded")

                # 等待页面关键元素或超时
                try:
                    page.wait_for_selector("video", timeout=10000)
                except PlaywrightTimeout:
                    pass

                # 从页面 HTML 提取 OG 元数据
                title = page.evaluate("""() => {
                    const el = document.querySelector('meta[property="og:title"]');
                    return el ? el.content : '';
                }""")
                desc = page.evaluate("""() => {
                    const el = document.querySelector('meta[property="og:description"]');
                    return el ? el.content : '';
                }""")
                cover = page.evaluate("""() => {
                    const el = document.querySelector('meta[property="og:image"]');
                    return el ? el.content : '';
                }""")
                author = page.evaluate("""() => {
                    const el = document.querySelector('meta[name="author"]') ||
                               document.querySelector('meta[property="og:article:author"]');
                    return el ? el.content : '';
                }""")
                video_url = page.evaluate("""() => {
                    const el = document.querySelector('meta[property="og:video:url"]');
                    return el ? el.content : '';
                }""")

                browser.close()

                if title or desc:
                    return VideoMeta(
                        title=title or desc or "未知标题",
                        author=author or "未知作者",
                        duration="",
                        likes=0,
                        comments=0,
                        shares=0,
                        cover_url=cover,
                        video_url=video_url or f"https://www.douyin.com/video/{aweme_id}",
                    )

        except PlaywrightTimeout:
            print(f"[通道2] Playwright 超时: {url}")
        except Exception as e:
            print(f"[通道2] Playwright 错误 ({url}): {type(e).__name__}: {str(e)}")

    return None


# ============== 通道 3 子函数：TikHub API ==============

async def _fetch_via_tikhub(aweme_id: str) -> Optional[VideoMeta]:
    """TikHub Web API 解析"""
    if not TIKHUB_API_KEY:
        return None

    headers = {"Authorization": f"Bearer {TIKHUB_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{TIKHUB_API_BASE}/douyin/web/fetch_one_video",
                params={"aweme_id": aweme_id},
                headers=headers
            )

        if response.status_code != 200:
            print(f"[通道3] TikHub HTTP {response.status_code}: {response.text[:200]}")
            return None

        data = response.json()
        if data.get("code") != 200 and data.get("status") != "success":
            print(f"[通道3] TikHub API 错误: {data.get('message', '')}")
            return None

        raw = data.get("data", {}) or data
        video_data = raw.get("aweme_detail", {}) or raw.get("aweme_info", {}) or raw

        desc = video_data.get("desc", "") or video_data.get("title", "") or "未知标题"
        author = (video_data.get("author", {}).get("nickname", "") or
                  video_data.get("nickname", "") or "未知作者")

        statistics = video_data.get("statistics", {}) or {}
        likes = statistics.get("digg_count", 0) or 0
        comments = statistics.get("comment_count", 0) or 0
        shares = statistics.get("share_count", 0) or 0

        video_info = video_data.get("video", {}) or {}
        cover_url = (
            video_info.get("cover", {}).get("url_list", [None])[0] or
            video_data.get("cover_image_url", "") or ""
        )
        play_addr = video_info.get("play_addr", {}) or {}
        video_url = play_addr.get("url_list", [None])[0] or ""
        if video_url and not video_url.startswith("http"):
            video_url = f"https://api.douyin.com/video/{video_url}"

        music_info = video_data.get("music", {}) or {}
        audio_url = (
            music_info.get("play_url", {}).get("url_list", [None])[0] or ""
        )

        duration_ms = video_data.get("duration", 0) or 0
        sec = duration_ms // 1000 if duration_ms > 1000 else duration_ms
        duration = f"{sec // 60:02d}:{sec % 60:02d}"

        return VideoMeta(
            title=desc,
            author=author,
            duration=duration,
            likes=likes,
            comments=comments,
            shares=shares,
            cover_url=cover_url,
            video_url=video_url,
            audio_url=audio_url,
        )

    except Exception as e:
        print(f"[通道3] TikHub 请求异常: {type(e).__name__}: {str(e)}")
        return None


# ============== 通道 4 子函数：ixigua 西瓜视频 ==============

async def _fetch_ixigua(aweme_id: str, attempt: int = 1) -> Optional[VideoMeta]:
    """
    通道 4：ixigua.com 西瓜视频解析
    字节系产品，CDN 风控比抖音弱很多。
    西瓜视频和抖音共用同一视频库，aweme_id 可以直接构造 ixigua 播放页。
    """
    ixigua_url = f"https://www.ixigua.com/{aweme_id}"

    user_agents = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    ]
    ua = user_agents[(attempt - 1) % len(user_agents)]

    try:
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": ua}) as client:
            # ixigua 也用 httpx 跟随重定向
            resp = await client.get(ixigua_url, follow_redirects=True)

            if resp.status_code != 200:
                print(f"[通道4] ixigua HTTP {resp.status_code}")
                return None

            html = resp.text

            # 提取标题
            title_match = re.search(r'<meta name="description" content="([^"]+)"', html)
            title = title_match.group(1) if title_match else ""
            if not title:
                title_match = re.search(r'<title>([^<]+)</title>', html)
                title = title_match.group(1) if title_match else "未知标题"

            # 提取封面
            cover_match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            cover_url = cover_match.group(1) if cover_match else ""

            # 提取视频 URL（ixigua 的视频直链通常在这里）
            video_match = re.search(r'"playAddr"\s*:\s*"([^"]+)"', html)
            video_url = video_match.group(1) if video_match else ""
            if video_url:
                video_url = video_url.replace("\\/", "/")

            # 提取作者
            author_match = re.search(r'"author"\s*:\s*"([^"]+)"', html)
            author = author_match.group(1) if author_match else "未知作者"

            if title:
                return VideoMeta(
                    title=title.strip(),
                    author=author.strip() if author else "未知作者",
                    duration="",
                    likes=0,
                    comments=0,
                    shares=0,
                    cover_url=cover_url,
                    video_url=video_url or ixigua_url,
                )

    except Exception as e:
        print(f"[通道4] ixigua 解析异常: {type(e).__name__}: {str(e)}")

    return None


# ============== Mock 逐字稿生成（保留，向后兼容）==============

def generate_mock_transcript(title: str = "", author: str = "") -> str:
    return f"""今天想跟大家分享一下{title if title else "如何养成好习惯"}

我觉得养成好习惯最重要的是坚持

比如说每天早睡早起

很多人说做不到

但其实只要你坚持二十一天

就能形成一个新的一惯性

我以前也是一个拖拖沓沓的人

后来通过这个小方法

真的改变了很多

首先你要设定一个小目标

不要一开始就想养成很多个习惯

从一个小习惯开始

比如每天阅读半小时

或者每天运动二十分钟

坚持一段时间之后

你就会发现

自己的生活慢慢在变好

好了今天的分享就到这里

如果对你有帮助

记得关注我

我们下期再见"""
