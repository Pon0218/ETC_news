import xml.etree.ElementTree as ET
import requests
import datetime
import time
import schedule
import traceback
from pymongo import MongoClient
from dotenv import dotenv_values
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage, BubbleContainer, BoxComponent, TextComponent, ImageComponent, ButtonComponent, URIAction
from linebot.exceptions import LineBotApiError

class CTSNewsLineNotifier:
    def __init__(self, xml_url, mongo_uri=None, mongo_db=None, line_bot_api=None):
        """
        初始化華視新聞LINE通知系統
        
        @param xml_url: 華視新聞XML RSS網址
        @param mongo_uri: MongoDB連接URI
        @param mongo_db: MongoDB資料庫名稱
        @param line_bot_api: 已初始化的LineBotApi實例
        """
        self.xml_url = xml_url
        self.mongo_uri = mongo_uri
        self.mongo_db_name = mongo_db
        
        # 初始化數據庫和LINE設定
        self.mongo_client = None
        self.db = None
        self.user_collection = None
        self.push_history_collection = None
        self.line_bot_api = line_bot_api
        
        # 設置數據庫連接
        self.setup_database()
        
    def setup_database(self):
        """連接MongoDB資料庫"""
        if not self.mongo_uri or not self.mongo_db_name:
            print("MongoDB連接信息缺失，請設置環境變量或直接提供參數")
            return
            
        try:
            self.mongo_client = MongoClient(self.mongo_uri)
            self.db = self.mongo_client[self.mongo_db_name]
            
            # 確認連接是否成功
            self.mongo_client.admin.command('ping')
            
            # 初始化集合（相當於SQL中的表）
            self.user_collection = self.db.user_preferences
            self.push_history_collection = self.db.push_history
            
            # 創建索引
            self.user_collection.create_index([("user_id", 1)], unique=True)
            self.push_history_collection.create_index([("user_id", 1), ("news_id", 1)])
            
            print(f"成功連接到 MongoDB: {self.mongo_db_name}")
        except Exception as e:
            print(f"MongoDB連接失敗: {e}")
            self.mongo_client = None
            self.db = None
            
    def fetch_xml_data(self):
        """從XML URL獲取RSS數據"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        try:
            print(f"正在獲取XML: {self.xml_url}")
            response = requests.get(self.xml_url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                print(f"成功獲取XML，內容長度: {len(response.text)} 字節")
                return response.text
            else:
                print(f"獲取XML失敗: HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"獲取XML時發生錯誤: {e}")
            return None
    
    def parse_xml(self, xml_data):
        """解析華視新聞XML格式"""
        if not xml_data:
            return []
        
        try:
            root = ET.fromstring(xml_data)
            
            # 尋找所有文章
            articles = root.findall('article')
            print(f"找到 {len(articles)} 篇文章")
            
            if not articles:
                # 如果沒有直接的article子元素，嘗試深度搜索
                articles = root.findall('.//article')
                print(f"深度搜索後找到 {len(articles)} 篇文章")
            
            news_items = []
            categories_found = set()
            
            for article in articles:
                # 提取新聞基本信息
                article_id = self.get_element_text(article, 'ID')
                
                # 提取標題 (可能在CDATA中)
                title_elem = article.find('title')
                title = ""
                if title_elem is not None:
                    if title_elem.text:
                        title = title_elem.text
                    else:
                        # 嘗試獲取CDATA
                        for child in title_elem:
                            if child.tag == 'CDATA' and child.text:
                                title = child.text
                                break
                
                # 提取類別
                category = self.get_element_text(article, 'category')
                if category:
                    categories_found.add(category)
                
                # 提取發布時間和更新時間
                publish_time_unix = self.get_element_text(article, 'publishTimeUnix')
                update_time_unix = self.get_element_text(article, 'updateTimeUnix')
                
                publish_time = self.show_datetime(publish_time_unix) if publish_time_unix else ""
                update_time = self.show_datetime(update_time_unix) if update_time_unix else ""
                
                # 提取縮略圖
                thumbnail = self.get_element_text(article, 'thumbnail')
                
                # 提取源URL
                source_url = self.get_element_text(article, 'sourceUrl')
                
                news_items.append({
                    'id': article_id,
                    'title': title,
                    'category': category,
                    'publish_time': publish_time,
                    'update_time': update_time,
                    'thumbnail': thumbnail,
                    'link': source_url,
                })
            
            print(f"找到的類別: {categories_found}")
            print(f"總共解析了 {len(news_items)} 篇文章")
            return news_items
        
        except Exception as e:
            print(f"解析XML時發生錯誤: {e}")
            traceback.print_exc()
            return []
    
    def get_element_text(self, parent, tag_name):
        """安全地獲取元素文本"""
        elem = parent.find(tag_name)
        if elem is not None and elem.text:
            return elem.text.strip()
        return ""
    
    def show_datetime(self, unix_time_ms):
        """將毫秒級Unix時間戳轉為可讀格式"""
        try:
            unix_time_sec = int(unix_time_ms) / 1000  # 轉換為秒
            dt = datetime.datetime.fromtimestamp(unix_time_sec)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return ""
    
    def get_latest_news(self):
        """即時獲取最新新聞，不儲存資料庫"""
        xml_data = self.fetch_xml_data()
        if not xml_data:
            return []
        
        news_items = self.parse_xml(xml_data)
        if not news_items:
            return []
            
        print(f"成功獲取 {len(news_items)} 篇最新新聞")
        return news_items
    
    def update_user_preference(self, user_id, categories):
        """更新用戶偏好設定
        
        @param user_id: LINE用戶ID
        @param categories: 用戶偏好的新聞類別列表，例如 ["政治", "社會", "國際"]
        """
        if not user_id or not self.mongo_client:
            return False
            
        now = datetime.datetime.now()
        
        # 使用upsert操作 - 如果不存在則創建，存在則更新
        result = self.user_collection.update_one(
            {"user_id": user_id}, 
            {
                "$set": {
                    "categories": categories,
                    "last_update": now
                }
            },
            upsert=True
        )
        
        if result.upserted_id:
            print(f"新增用戶 {user_id} 的偏好設定: {categories}")
        else:
            print(f"更新用戶 {user_id} 的偏好設定: {categories}")
            
        return True
    
    def get_user_preferences(self, user_id=None):
        """獲取用戶偏好設定
        
        @param user_id: 若提供，則獲取特定用戶的偏好；否則獲取所有用戶的偏好
        @return: 用戶偏好字典，格式為 {user_id: {"categories": [...], "last_update": ...}}
        """
        if not self.mongo_client:
            return {}
            
        result = {}
        
        if user_id:
            # 獲取特定用戶
            user_doc = self.user_collection.find_one({"user_id": user_id})
            if user_doc:
                result[user_id] = {
                    "categories": user_doc.get("categories", []),
                    "last_update": user_doc.get("last_update")
                }
        else:
            # 獲取所有用戶
            for user_doc in self.user_collection.find():
                result[user_doc["user_id"]] = {
                    "categories": user_doc.get("categories", []),
                    "last_update": user_doc.get("last_update")
                }
        
        return result
    
    def get_news_by_preference(self, user_id, limit=10):
        """根據用戶偏好即時獲取新聞
        
        @param user_id: LINE用戶ID
        @param limit: 獲取新聞數量限制
        @return: 符合偏好的新聞列表
        """
        # 獲取用戶偏好
        preferences = self.get_user_preferences(user_id)
        user_categories = preferences.get(user_id, {}).get("categories", []) if preferences else []
        
        # 獲取最新新聞
        all_news = self.get_latest_news() or []
        if not all_news:
            return []
        
        # 如果用戶沒有偏好，直接返回最新新聞
        if not user_categories:
            return all_news[:limit]
        
        # 獲取推送歷史中的新聞ID
        pushed_news_ids = set()
        if self.mongo_client:
            pushed_history = list(self.push_history_collection.find(
                {"user_id": user_id},
                {"news_id": 1, "_id": 0}
            ))
            pushed_news_ids = {item["news_id"] for item in pushed_history}
        
        # 按類別分組
        filtered_news_by_category = {category: [] for category in user_categories}
        
        # 將新聞分配到對應類別
        for news in all_news:
            if news['id'] in pushed_news_ids:
                continue
                
            category = news['category']
            if category in user_categories:
                filtered_news_by_category[category].append(news)
        
        # 平均分配每個類別的新聞
        result_news = []
        if user_categories:
            # 計算每個類別的基本配額
            quota_per_category = max(1, limit // len(user_categories))
            remaining = limit
            
            # 第一輪：分配基本配額
            for category in user_categories:
                category_news = filtered_news_by_category.get(category, [])
                news_to_add = min(quota_per_category, len(category_news), remaining)
                result_news.extend(category_news[:news_to_add])
                remaining -= news_to_add
            
            # 第二輪：分配剩餘配額
            if remaining > 0:
                category_index = 0
                categories = list(user_categories)
                while remaining > 0 and category_index < len(categories):
                    category = categories[category_index]
                    category_news = filtered_news_by_category.get(category, [])
                    already_added = min(quota_per_category, len(category_news))
                    
                    if already_added < len(category_news):
                        result_news.append(category_news[already_added])
                        remaining -= 1
                        # 不增加category_index，繼續在同一類別分配
                    else:
                        category_index += 1
        
        # 如果還不夠，用其他未推送過的新聞填充（確保不重複添加）
        if len(result_news) < limit:
            used_news_ids = {news['id'] for news in result_news}
            other_news = []
            
            # 遍歷所有新聞，找出未被使用過且未推送過的
            for news in all_news:
                if (news['id'] not in pushed_news_ids and 
                    news['id'] not in used_news_ids and
                    news not in result_news):  # 額外檢查防止重複
                    other_news.append(news)
                    used_news_ids.add(news['id'])  # 更新已使用ID集合
                    
                    # 達到所需數量就停止
                    if len(other_news) >= (limit - len(result_news)):
                        break
                        
            result_news.extend(other_news)
        
        return result_news[:limit]
    
    def create_news_flex_message(self, news_items):
        """建立LINE Flex訊息 - 橫排新聞列表格式
        
        @param news_items: 新聞項目列表
        @return: Flex訊息物件
        """
        if not news_items:
            return TextSendMessage(text="沒有找到符合偏好的新聞")
        
        # 創建主要容器
        bubble = {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "今日重點新聞",
                        "weight": "bold",
                        "size": "xl",
                        "margin": "md"
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "lg",
                        "spacing": "sm",
                        "contents": []
                    }
                ]
            }
        }
        
        # 新聞容器
        news_container = bubble["body"]["contents"][1]
        
        # 為每則新聞創建橫排項目
        for i, news in enumerate(news_items):
            # 新聞框
            news_box = {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    # 左側方形圖片 - 優化填滿設定
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {
                                "type": "image",
                                "url": news.get('thumbnail') if news.get('thumbnail') else "https://via.placeholder.com/100x100.png?text=CTS+News",
                                "aspectMode": "cover",
                                "aspectRatio": "1:1",
                                "size": "full",
                                "gravity": "center"
                            }
                        ],
                        "flex": 1,
                        "width": "30%",
                        "backgroundColor": "#eeeeee",
                        "cornerRadius": "md"
                    },
                    # 右側類別和標題
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            # 類別標籤
                            {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {
                                        "type": "text",
                                        "text": news.get('category', '即時'),
                                        "size": "xs",
                                        "color": "#ffffff",
                                        "align": "center",
                                        "gravity": "center"
                                    }
                                ],
                                "backgroundColor": "#06C755",
                                "cornerRadius": "sm",
                                "paddingAll": "2px",
                                "paddingStart": "4px",
                                "paddingEnd": "4px",
                                "width": "60px"
                            },
                            # 標題
                            {
                                "type": "text",
                                "text": news.get('title', ''),
                                "size": "sm",
                                "color": "#111111",
                                "margin": "sm",
                                "align": "start",
                                "gravity": "top",
                                "wrap": True,
                                "weight": "regular",
                                "maxLines": 3
                            }
                        ],
                        "spacing": "sm",
                        "paddingStart": "12px",
                        "paddingEnd": "12px",
                        "paddingTop": "12px",
                        "paddingBottom": "12px",
                        "flex": 2,
                        "justifyContent": "flex-start"
                    }
                ],
                "spacing": "md",
                "paddingAll": "0px",
                "height": "100px",
                "backgroundColor": "#FFFFFF",
                "cornerRadius": "md",
                "margin": "md",
                "action": {
                    "type": "uri",
                    "label": "action",
                    "uri": news.get('link', 'https://news.cts.com.tw/')
                }
            }
            
            # 如果不是最後一則新聞，添加分隔線
            if i < len(news_items) - 1:
                news_container["contents"].append(news_box)
                news_container["contents"].append({
                    "type": "separator",
                    "margin": "sm"
                })
            else:
                news_container["contents"].append(news_box)
        
        return FlexSendMessage(
            alt_text="今日重點新聞",
            contents=bubble
        )
    
    def push_news_to_user(self, user_id, news_count=10):
        """推送新聞給用戶
        
        @param user_id: LINE用戶ID
        @param news_count: 推送的新聞數量
        @return: 推送結果
        """
        if not self.line_bot_api:
            return "LINE API未設置"
        
        # 獲取用戶偏好的新聞
        news_items = self.get_news_by_preference(user_id, news_count)
        if not news_items:
            print(f"沒有找到用戶 {user_id} 偏好的新聞")
            return "沒有找到符合偏好的新聞"
        
        push_time = datetime.datetime.now()
        
        try:
            # 1. 發送問候訊息
            greeting_message = "早安！以下是今天的重點新聞："
            self.line_bot_api.push_message(user_id, TextSendMessage(text=greeting_message))
            
            # 2. 發送新聞列表 (所有新聞在一條Flex Message中)
            flex_message = self.create_news_flex_message(news_items)
            self.line_bot_api.push_message(user_id, flex_message)
            
            # 記錄推送歷史到MongoDB
            if self.mongo_client:
                for item in news_items:
                    self.push_history_collection.insert_one({
                        "user_id": user_id,
                        "news_id": item['id'],
                        "push_time": push_time,
                        "news_title": item['title'],
                        "news_category": item['category']
                    })
            
            print(f"成功推送 {len(news_items)} 則新聞給用戶 {user_id}")
            return f"成功推送 {len(news_items)} 則新聞"
            
        except LineBotApiError as e:
            print(f"推送新聞時發生錯誤: {e}")
            return f"推送失敗: {str(e)}"
    
    def daily_morning_push(self):
        """每日早上推送新聞給所有用戶"""
        print(f"開始執行每日早上新聞推送任務: {datetime.datetime.now()}")
        
        # 獲取所有用戶
        user_preferences = self.get_user_preferences()
        if not user_preferences:
            print("沒有找到用戶")
            return
        
        # 逐一推送 (不需先更新資料庫，因為每次都會即時獲取)
        for user_id in user_preferences:
            result = self.push_news_to_user(user_id, 10)
            print(f"用戶 {user_id} 推送結果: {result}")
            time.sleep(1)  # 避免過於頻繁的API調用
    
    def start_scheduler(self):
        """啟動排程器"""
        # 設定每天早上7點執行推送任務
        schedule.every().day.at("07:00").do(self.daily_morning_push)
        
        print("排程器已啟動，將在每天早上7:00推送新聞")
        
        # 無限循環執行排程任務
        while True:
            schedule.run_pending()
            time.sleep(60)  # 每分鐘檢查一次排程


# 使用示例
if __name__ == "__main__":
    # 從.env文件載入配置
    config = dotenv_values("./.env")
    
    # 華視新聞RSS網址
    xml_url = "https://news.cts.com.tw/api/lineToday.xml"
    
    # 從配置中獲取MongoDB連接信息
    mongo_uri = config.get('MONGODB_URI', "mongodb+srv://Pon0218:Kone2204@terry.ctsk7aj.mongodb.net/")
    mongo_db = config.get('MONGODB_DB', "cts_news_system")
    
    # 從配置中獲取LINE API信息
    line_channel_access_token = config.get('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
    line_channel_secret = config.get('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')
    
    # 初始化LINE Bot API
    line_bot_api = LineBotApi(line_channel_access_token)
    
    # 建立通知器實例
    notifier = CTSNewsLineNotifier(xml_url, mongo_uri, mongo_db, line_bot_api)
    
    # 示例: 添加一個測試用戶及其偏好
    test_user_id = "U1234567890abcdef1234567890abcdef"  # 測試用戶ID
    notifier.update_user_preference(test_user_id, ["政治", "社會", "國際"])
    
    # 示例: 立即為測試用戶推送新聞
    result = notifier.push_news_to_user(test_user_id)
    print(result)
    
    # 啟動排程器(取消註解以啟用)
    # notifier.start_scheduler()