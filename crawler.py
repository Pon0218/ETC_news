import requests
import random
import time
import re
import os
import json
from datetime import datetime
from bs4 import BeautifulSoup
import sys
import io

# 設定標準輸出的編碼
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 新聞類別列表
NEWS_CATEGORIES = [
    "即時", "氣象", "政治", "打假特攻隊", "MLB", "國際", "社會", "運動", 
    "生活", "財經", "台語", "地方", "產業", "綜合", "藝文", "旅遊", "專題"
]

# 類別URL對應
CATEGORY_URLS = {
    "即時": "https://news.cts.com.tw/real/index.html",
    "氣象": "https://news.cts.com.tw/weather/index.html",
    "政治": "https://news.cts.com.tw/politics/index.html",
    "MLB": "https://news.cts.com.tw/mlb/index.html",
    "國際": "https://news.cts.com.tw/international/index.html",
    "社會": "https://news.cts.com.tw/society/index.html",
    "運動": "https://news.cts.com.tw/sports/index.html",
    "生活": "https://news.cts.com.tw/life/index.html",
    "財經": "https://news.cts.com.tw/money/index.html",
    "台語": "https://news.cts.com.tw/taiwanese/index.html",
    "地方": "https://news.cts.com.tw/local/index.html",
    "產業": "https://news.cts.com.tw/industry/index.html",
    "綜合": "https://news.cts.com.tw/general/index.html",
    "藝文": "https://news.cts.com.tw/arts/index.html",
    "旅遊": "https://news.cts.com.tw/travel/index.html",
    "專題": "https://news.cts.com.tw/subject/index.html"
}

def get_random_user_agent():
    """獲取隨機User-Agent"""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
    ]
    return random.choice(user_agents)

def fetch_news(category="即時", count=10):
    """
    從華視新聞網爬取指定類別的新聞列表
    :param category: 新聞類別
    :param count: 新聞數量
    :return: 新聞列表 [{'title': '...', 'url': '...'}]
    """
    news_items = []
    
    try:
        # 獲取對應類別的URL
        url = CATEGORY_URLS.get(category)
        if not url:
            print(f"無法找到 {category} 類別的URL")
            return news_items
        
        # 設置請求頭
        headers = {
            "User-Agent": get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://news.cts.com.tw/",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0"
        }

        print(f"正在從 {url} 獲取 {category} 新聞...")
        
        # 添加隨機延遲，避免頻繁請求
        time.sleep(random.uniform(1, 3))
        
        # 發送請求時增加重試機制
        session = requests.Session()
        retries = 3
        for attempt in range(retries):
            try:
                response = session.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                print(f"請求失敗 (嘗試 {attempt+1}/{retries}): {e}")
                if attempt == retries - 1:
                    raise
                time.sleep(random.uniform(2, 5))
                
        # 確認是否獲取到內容
        if not response.text:
            print("警告: 獲取到空的回應")
            return []
            
        # 使用 BeautifulSoup 解析 HTML
        soup = BeautifulSoup(response.content, 'html.parser', from_encoding='utf-8')
        
        # 找到新聞項目 - 嘗試多種選擇器，增加適應性
        news_blocks = soup.select('.newsItems-wrapper .newsItems-item')
        
        # 如果第一種選擇器沒找到結果，嘗試其他可能的選擇器
        if not news_blocks:
            news_blocks = soup.select('.news-list .news-item')
        
        if not news_blocks:
            news_blocks = soup.select('article.news')
            
        # 如果仍然沒有找到新聞項目，嘗試更通用的方法
        if not news_blocks:
            # 尋找所有可能的新聞連結
            potential_news = soup.find_all('a', href=re.compile(r'/cts/.*?/\d+/\d+\d+\.html'))
            
            # 轉換為適合處理的格式
            for link in potential_news[:count]:
                title = link.get_text().strip()
                news_url = link['href']
                if title and news_url:
                    if not news_url.startswith('http'):
                        news_url = f"https://news.cts.com.tw{news_url}"
                    
                    # 避免重複
                    if not any(item['url'] == news_url for item in news_items):
                        news_items.append({
                            "title": title,
                            "url": news_url
                        })
            
            # 如果找到了足夠的新聞項目，就返回
            if len(news_items) >= count:
                return news_items[:count]
        
        # 處理標準格式的新聞項目
        for i, news_block in enumerate(news_blocks[:count*2]):  # 獲取更多，以防有些解析失敗
            # 嘗試多種可能的標題選擇器
            title_element = None
            for selector in ['.newsItems-item-title a', '.news-title a', 'h3 a', '.title a']:
                title_element = news_block.select_one(selector)
                if title_element:
                    break
            
            if not title_element:
                # 如果沒有找到標題元素，嘗試查找任何帶href的a標籤
                title_element = news_block.find('a', href=True)
            
            if title_element:
                title = title_element.text.strip()
                news_url = title_element['href']
                if not news_url.startswith('http'):
                    news_url = f"https://news.cts.com.tw{news_url}"
                
                # 避免空標題和重複的新聞
                if title and not any(item['url'] == news_url for item in news_items):
                    news_items.append({
                        "title": title,
                        "url": news_url
                    })
                    
                    # 如果已經獲取了足夠的新聞，則退出循環
                    if len(news_items) >= count:
                        break
        
        # 如果沒有找到新聞，記錄錯誤
        if not news_items and category in CATEGORY_URLS:
            print(f"未能從華視新聞網獲取 {category} 類別的新聞。請檢查網站結構是否已變更。")
    
    except Exception as e:
        print(f"獲取 {category} 新聞時發生錯誤: {e}")
        return []
    
    return news_items

def extract_news_details(url):
    """
    從單一新聞頁面提取詳細資訊
    :param url: 新聞頁面URL
    :return: 包含詳細資訊的字典
    """
    headers = {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    
    try:
        # 增加重試機制
        session = requests.Session()
        retries = 3
        for attempt in range(retries):
            try:
                response = session.get(url, headers=headers, timeout=15)
                response.encoding = 'utf-8'
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                print(f"請求 {url} 失敗 (嘗試 {attempt+1}/{retries}): {e}")
                if attempt == retries - 1:
                    raise
                time.sleep(random.uniform(2, 5))
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 提取標題
        title_element = soup.select_one('h1.artical-title')
        if not title_element:
            title_element = soup.select_one('h1.article-title')  # 嘗試替代選擇器
        title_text = title_element.text.strip() if title_element else "無標題"
        
        # 提取發布時間
        time_element = soup.select_one('time.artical-time')
        if not time_element:
            time_element = soup.select_one('.time')
        
        published_time = None
        if time_element:
            # 優先使用 datetime 屬性
            if 'datetime' in time_element.attrs:
                published_time = time_element['datetime']
            else:
                published_time = time_element.text.strip()
                
        # 格式化時間
        if published_time:
            try:
                # 嘗試處理不同的時間格式
                if 'T' in published_time:
                    # 2025/04/09T09:48:00+08:00 格式
                    dt = datetime.fromisoformat(published_time.replace('/', '-'))
                    published_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                elif '/' in published_time:
                    # 2025/04/09 09:48 格式
                    dt = datetime.strptime(published_time, "%Y/%m/%d %H:%M")
                    published_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError) as e:
                print(f"處理時間格式時出錯: {e}, 時間字串: {published_time}")
                # 如果轉換失敗，保留原始字串
                pass
        
        # 如果沒有找到時間，使用當前時間
        if not published_time:
            published_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 提取記者和地點信息
        reporter_element = soup.select_one('.reporter p')
        if not reporter_element:
            reporter_element = soup.select_one('.author')
            
        reporter_info = reporter_element.text.strip() if reporter_element else "未知記者"
        
        # 解析記者和地點
        reporter = "未知"
        location = "未知"
        if reporter_info:
            reporter_match = re.search(r'(.+?)\s*報導', reporter_info)
            reporter = reporter_match.group(1).strip() if reporter_match else "未知"
            
            location_match = re.search(r'/\s*(.+)\s*$', reporter_info)
            location = location_match.group(1).strip() if location_match else "未知"
        
        # 提取新聞內容 (多個 p 標籤)
        content_container = soup.select_one('.artical-content')
        if not content_container:
            content_container = soup.select_one('.article-content')
            
        content = ""
        if content_container:
            # 獲取所有段落
            paragraphs = content_container.select('p')
            if paragraphs:
                content = "\n\n".join([p.text.strip() for p in paragraphs if p.text.strip()])
            else:
                # 如果沒有 p 標籤，直接獲取所有文本
                content = content_container.text.strip()
        
        # 檢查是否有影片
        has_video = False
        video_url = ""
        
        # 檢查常見的影片容器
        video_containers = [
            soup.select_one('.ytp-cued-thumbnail-overlay-image'),
            soup.select_one('.video-container'),
            soup.select_one('iframe[src*="youtube"]')
        ]
        
        for container in video_containers:
            if container:
                has_video = True
                if container.name == 'iframe' and 'src' in container.attrs:
                    video_url = container['src']
                    break
                elif container.get('style') and 'url' in container.get('style'):
                    # 從 style 屬性中提取 URL
                    url_match = re.search(r'url\("(.+?)"\)', container.get('style'))
                    if url_match:
                        thumbnail_url = url_match.group(1)
                        # 從縮略圖URL嘗試構建YouTube影片URL
                        video_id_match = re.search(r'/vi(?:_webp)?/([^/]+)/', thumbnail_url)
                        if video_id_match:
                            video_id = video_id_match.group(1)
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                            break
        
        # 組合結果
        news_data = {
            "title": title_text,
            "url": url,
            "published_time": published_time,
            "reporter": reporter,
            "location": location,
            "content": content,
            "has_video": has_video,
            "video_url": video_url,
            "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        return news_data
        
    except Exception as e:
        print(f"提取新聞詳細資訊時發生錯誤: {e}")
        import traceback
        traceback.print_exc()
        return None

def crawl_category_news(category="即時", count=10, json_folder="data"):
    """
    爬取特定類別的新聞並保存為JSON
    :param category: 新聞類別
    :param count: 新聞數量
    :param json_folder: JSON檔案存放的資料夾
    :return: 詳細新聞列表
    """
    print(f"開始爬取 {category} 類別的新聞...")
    
    # 步驟1: 從分類頁面獲取新聞列表
    news_list = fetch_news(category, count)
    
    if not news_list:
        print(f"未找到 {category} 類別的新聞")
        return []
    
    print(f"找到 {len(news_list)} 則 {category} 新聞標題和連結")
    
    # 步驟2: 對每個新聞連結獲取詳細內容
    detailed_news = []
    
    for i, news_item in enumerate(news_list):
        url = news_item["url"]
        print(f"({i+1}/{len(news_list)}) 正在提取詳細資訊: {url}")
        
        # 避免頻繁請求網站
        time.sleep(random.uniform(1, 3))
        
        # 獲取詳細資訊
        try:
            news_details = extract_news_details(url)
            
            if news_details:
                # 添加類別資訊
                news_details["category"] = category
                detailed_news.append(news_details)
        except Exception as e:
            print(f"處理新聞 {url} 時出錯: {e}")
    
    # 步驟3: 保存為JSON
    if detailed_news:
        # 確保目錄存在
        os.makedirs(json_folder, exist_ok=True)
        
        # 建立檔名，包含時間戳記
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_filename = f"{json_folder}/news_{category}_{timestamp}.json"
        
        # 保存檔案
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(detailed_news, f, ensure_ascii=False, indent=4)
        print(f"已將 {len(detailed_news)} 則 {category} 新聞保存至 {json_filename}")
    
    return detailed_news

def crawl_all_categories(categories=None, count_per_category=5, json_folder="data"):
    """爬取多個類別的新聞"""
    if categories is None:
        categories = NEWS_CATEGORIES
    
    all_news = {}
    
    # 確保目錄存在
    os.makedirs(json_folder, exist_ok=True)
    
    # 建立一個總匯總檔案名稱
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_filename = f"{json_folder}/all_news_{timestamp}.json"
    
    for category in categories:
        print(f"\n{'='*50}\n爬取 {category} 類別\n{'='*50}")
        news = crawl_category_news(category, count_per_category, json_folder)
        all_news[category] = news
        
        # 在類別之間添加較長的延遲
        if category != categories[-1]:
            delay = random.uniform(5, 10)
            print(f"等待 {delay:.2f} 秒後爬取下一個類別...")
            time.sleep(delay)
    
    # 保存所有類別的新聞到一個檔案
    with open(summary_filename, "w", encoding="utf-8") as f:
        json.dump(all_news, f, ensure_ascii=False, indent=4)
    
    print(f"\n所有類別的新聞已保存至 {summary_filename}")
    
    return all_news

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='華視新聞爬蟲 (僅保存JSON)')
    parser.add_argument('--category', type=str, default="即時", help='指定爬取的新聞類別')
    parser.add_argument('--count', type=int, default=10, help='每個類別爬取的新聞數量')
    parser.add_argument('--all', action='store_true', help='爬取所有類別')
    parser.add_argument('--folder', type=str, default="data", help='JSON檔案保存的資料夾')
    
    args = parser.parse_args()
    
    if args.all:
        print(f"開始爬取所有類別的新聞，每個類別 {args.count} 則")
        crawl_all_categories(count_per_category=args.count, json_folder=args.folder)
    else:
        print(f"開始爬取 {args.category} 類別的新聞，數量 {args.count} 則")
        crawl_category_news(args.category, args.count, args.folder)