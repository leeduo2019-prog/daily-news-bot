import feedparser
import requests
import datetime
import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import re
import sys

# 配置读取
DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

RSS_FEEDS = {
    "🇨🇳 国内财经": [
        "https://finance.sina.com.cn/roll/index.d.html?cid=56588&page=1&rss=0&num=20", # 新浪财经
        "https://www.jiemian.com/rss/", # 界面新闻
        "https://www.eastmoney.com/rss.xml", # 东方财富
    ],
    "🇨🇳 国内大事": [
        "https://feed.thepaper.cn/www/channel/25953", # 澎湃新闻-时政
        "http://www.xinhuanet.com/politics/xhsxw.xml", # 新华网-时政
    ],
    "🌍 国际大事": [
        "http://feeds.bbci.co.uk/news/world/rss.xml", # BBC World
        "https://www.aljazeera.com/xml/rss/all.xml", # 半岛电视台
        "https://apnews.com/rss/world-news", # AP News
    ],
    "💻 技术前沿": [
        "https://www.ithome.com/rss/", # IT之家
        "https://www.infoq.cn/feed/", # InfoQ
    ]
}

HN_API = "https://hacker-news.firebaseio.com/v0/topstories.json"

def get_dingtalk_sign():
    """生成钉钉加签签名"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f'{timestamp}\n{DINGTALK_SECRET}'
    hmac_code = hmac.new(
        DINGTALK_SECRET.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign

def send_dingtalk(content, is_error=False):
    """发送钉钉消息"""
    if not DINGTALK_WEBHOOK:
        print("⚠️ 未配置 DINGTALK_WEBHOOK，跳过发送")
        return

    try:
        timestamp, sign = get_dingtalk_sign()
        url = f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"
        
        # 钉钉 Markdown 限制 20KB，做安全截断
        if len(content) > 18000:
            content = content[:17900] + "\n\n> ... (内容过长已截断)"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": "📰 每日新闻聚合" if not is_error else "⚠️ 爬虫告警",
                "text": content
            }
        }
        
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
        result = res.json()
        if result.get("errcode") != 0:
            print(f"❌ 钉钉发送失败: {result}")
        else:
            print("✅ 钉钉消息发送成功")
    except Exception as e:
        print(f"❌ 钉钉请求异常: {e}")

def fetch_rss(url, max_items=4):
    """抓取单个 RSS 源"""
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            return []
        
        items = []
        for entry in feed.entries[:max_items]:
            title = entry.get('title', '无标题')
            link = entry.get('link', '#')
            items.append({"title": title, "link": link})
        return items
    except Exception as e:
        print(f"⚠️ RSS 抓取失败 {url}: {e}")
        return []

def fetch_hacker_news(max_items=5):
    """抓取 Hacker News 热门"""
    try:
        res = requests.get(HN_API, timeout=10)
        res.raise_for_status()
        top_ids = res.json()[:max_items]
        
        items = []
        for story_id in top_ids:
            try:
                story_res = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=5)
                if story_res.ok:
                    story = story_res.json()
                    title = story.get('title', '')
                    url = story.get('url', f"https://news.ycombinator.com/item?id={story_id}")
                    items.append({"title": title, "link": url, "summary": ""})
            except:
                continue
        return items
    except Exception as e:
        print(f"⚠️ Hacker News 抓取失败: {e}")
        return []

def build_markdown(news_data, is_error=False):
    """构建 Markdown 内容"""
    if is_error:
        return f"""## ⚠️ 今日新闻抓取失败

> 时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
> 
> 原因: 多个数据源抓取失败或网络异常。
> 
> 请检查 GitHub Actions 日志或源站状态。"""

    today = datetime.date.today().strftime("%Y-%m-%d")
    now = datetime.datetime.now().strftime("%H:%M")
    
    md = f"### 📰 每日新闻聚合 - {today}\n"
    md += f"> 生成时间: {now} (北京时间)\n\n"
    
    for category, items in news_data.items():
        if items:
            md += f"**{category}**\n"
            for item in items:
                md += f"- [{item['title']}]({item['link']})\n"
            md += "\n"
            
    return md

def main():
    print("🚀 开始抓取新闻...")
    all_news = {}
    success_count = 0
    
    try:
        for category, urls in RSS_FEEDS.items():
            print(f"📡 抓取: {category}")
            category_items = []
            for url in urls:
                category_items.extend(fetch_rss(url, max_items=4))
            
            # 去重
            seen = set()
            unique_items = []
            for item in category_items:
                if item['title'] not in seen:
                    seen.add(item['title'])
                    unique_items.append(item)
            
            all_news[category] = unique_items[:6]  # 每类最多 6 条
            if unique_items:
                success_count += 1

        # Hacker News
        print("📡 抓取: Hacker News")
        hn_items = fetch_hacker_news(max_items=5)
        if hn_items:
            all_news["🤖 Hacker News 热门"] = hn_items
            success_count += 1

        # 判断是否成功
        if success_count < 2:  # 至少 2 个分类成功
            print("⚠️ 抓取成功率过低，发送失败告警")
            send_dingtalk(build_markdown({}, is_error=True), is_error=True)
            sys.exit(1)

        # 生成并发送
        content = build_markdown(all_news)
        send_dingtalk(content)
        
        # 本地保存
        with open("news.md", "w", encoding="utf-8") as f:
            f.write(content)
        print("✅ 新闻抓取完成")
        
    except Exception as e:
        print(f"❌ 主流程异常: {e}")
        send_dingtalk(build_markdown({}, is_error=True), is_error=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
