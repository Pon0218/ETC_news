import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    PostbackEvent, MessageAction, FlexSendMessage, BubbleContainer, BoxComponent,
    ButtonComponent, TextComponent, RichMenu, RichMenuArea, RichMenuBounds, RichMenuSize
)
import pymongo
from pymongo import MongoClient
from dotenv import dotenv_values
import xml.etree.ElementTree as ET
from datetime import datetime
import requests

app = Flask(__name__)

# 載入環境變數
config = dotenv_values("./.env")
LINE_CHANNEL_SECRET = config.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = config.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 設定 MongoDB Atlas
mongo_uri = config.get('MONGODB_URI')
mongo_db = config.get('MONGODB_DB')
client = MongoClient(mongo_uri)
db = client[mongo_db]
users_collection = db['users']

# 定義新聞類別
NEWS_CATEGORIES = [
    "即時", "氣象", "政治", "MLB", "國際", "社會", 
    "運動", "生活", "財經", "地方", "產業", "綜合", 
    "藝文", "旅遊", "專題"
]

# 全局變量來跟踪用戶上下文
user_context = {}

@app.route("/callback", methods=['POST'])
def callback():
    # 獲取 X-Line-Signature 頭部值
    signature = request.headers['X-Line-Signature']

    # 獲取請求內容
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # 處理 webhook 回調
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text
    user_id = event.source.user_id
    reply_token = event.reply_token
    
    if text == "類別搜尋":
        # 顯示類別搜尋選單
        user_context[user_id] = "category_search"  # 設置上下文為搜尋模式
        show_category_search(reply_token)
    elif text == "偏好設定":
        # 顯示偏好設定選單
        user_context[user_id] = "preference_setting"  # 設置上下文為偏好設定模式
        show_preference_settings(reply_token, user_id)
    elif text == "幫助":
        # 顯示幫助信息
        show_help(reply_token)
    elif text == "全選偏好":
        # 全選所有類別
        update_user_preferences(user_id, NEWS_CATEGORIES)
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="已為您選擇所有新聞類別！")
        )
    elif text == "清除偏好":
        # 清除所有偏好
        update_user_preferences(user_id, [])
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="已清除所有偏好設定！")
        )
    else:
        # 嘗試處理類別的搜尋或偏好切換
        if text in NEWS_CATEGORIES:
            # 判斷是搜尋還是偏好切換的標誌
            context = user_context.get(user_id, "")
            
            if context == "category_search":
                # 搜尋該類別的新聞
                try:
                    news_list = get_news_by_category(text, 10)  # 獲取最新10篇新聞
                    if news_list:
                        # 顯示新聞列表
                        show_news_list(reply_token, text, news_list)
                    else:
                        line_bot_api.reply_message(
                            reply_token,
                            TextSendMessage(text=f"未找到「{text}」類別的新聞，請稍後再試。")
                        )
                except Exception as e:
                    print(f"獲取新聞時發生錯誤: {e}")
                    import traceback
                    traceback.print_exc()
                    line_bot_api.reply_message(
                        reply_token,
                        TextSendMessage(text=f"獲取新聞時發生錯誤，請稍後再試。")
                    )
            else:
                # 切換偏好設定
                toggle_user_preference(user_id, text)
                user_prefs = get_user_preferences(user_id)
                if text in user_prefs:
                    message = f"已新增「{text}」到您的偏好！"
                else:
                    message = f"已從您的偏好中移除「{text}」！"
                
                line_bot_api.reply_message(
                    reply_token,
                    TextSendMessage(text=message)
                )
        else:
            # 顯示主選單提示
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text="請使用圖文選單選擇功能，或輸入「類別搜尋」、「偏好設定」或「幫助」。")
            )

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    reply_token = event.reply_token
    data = event.postback.data
    
    if data.startswith('category_'):
        # 處理類別選擇
        category = data.replace('category_', '')
        toggle_user_preference(user_id, category)
        
        # 取得使用者目前偏好
        user_prefs = get_user_preferences(user_id)
        if category in user_prefs:
            message = f"已新增「{category}」到您的偏好！"
        else:
            message = f"已從您的偏好中移除「{category}」！"
        
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=message)
        )
    elif data == 'set_preferences':
        # 顯示設定偏好的詳細選單
        show_preference_details(reply_token, user_id)

def get_news_by_category(category, count=10):
    """從自定義XML RSS源獲取指定類別的最新新聞"""
    try:
        # 獲取RSS內容
        response = requests.get("https://news.cts.com.tw/api/lineToday.xml")
        
        if response.status_code != 200:
            print(f"獲取RSS失敗: {response.status_code}")
            return []
        
        # 解析XML
        xml_content = response.text
        
        # 使用ElementTree解析XML
        root = ET.fromstring(xml_content)
        
        # 找到所有文章
        articles = root.findall('.//article')
        
        news_list = []
        for article in articles:
            # 獲取文章類別
            article_category = article.find('category')
            if article_category is not None and article_category.text == category:
                # 提取文章信息
                title_elem = article.find('title')
                title = title_elem.text if title_elem is not None else "無標題"
                
                # 清理CDATA
                if title and '![CDATA[' in title:
                    title = title.replace('![CDATA[', '').replace(']]>', '')
                
                # 獲取ID
                id_elem = article.find('ID')
                article_id = id_elem.text if id_elem is not None else ""
                
                # 構建鏈接
                link = f"https://news.cts.com.tw/cts/politics/{article_id[:6]}/{article_id}.html"
                
                # 獲取縮略圖
                thumbnail_elem = article.find('thumbnail')
                thumbnail = thumbnail_elem.text if thumbnail_elem is not None else ""
                
                # 獲取發布時間
                publish_time_elem = article.find('publishTimeUnix')
                publish_time = ""
                if publish_time_elem is not None and publish_time_elem.text:
                    try:
                        # 轉換Unix時間戳為可讀時間
                        timestamp = int(publish_time_elem.text) / 1000  # 轉為秒
                        publish_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')
                    except:
                        publish_time = ""
                
                news_list.append({
                    "title": title,
                    "link": link,
                    "published": publish_time,
                    "thumbnail": thumbnail,
                    "category": category
                })
                
                # 如果已經找到足夠數量的新聞，停止查找
                if len(news_list) >= count:
                    break
        
        return news_list
    except Exception as e:
        print(f"解析RSS時發生錯誤: {e}")
        import traceback
        traceback.print_exc()
        return []

def show_news_list(reply_token, category, news_list):
    """顯示新聞列表，使用提供的樣式模板"""
    
    bubble = {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"{category}類別新聞",
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
    for i, news in enumerate(news_list[:10]):  # 最多顯示10則新聞
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
                                    "text": category,
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
        if i < len(news_list[:10]) - 1:
            news_container["contents"].append(news_box)
            news_container["contents"].append({
                "type": "separator",
                "margin": "sm"
            })
        else:
            news_container["contents"].append(news_box)
    
    # 創建並發送Flex消息
    flex_message = FlexSendMessage(
        alt_text=f"{category}類別新聞",
        contents=bubble
    )
    
    line_bot_api.reply_message(reply_token, flex_message)

def show_category_search(reply_token):
    """顯示類別搜尋選單，使用橫向泡泡"""
    # 將類別分組，分別為5、5、5
    category_groups = [
        NEWS_CATEGORIES[0:5],
        NEWS_CATEGORIES[5:10],
        NEWS_CATEGORIES[10:15]
    ]
    
    bubbles = []
    
    for group in category_groups:
        buttons = []
        
        for category in group:
            buttons.append(
                ButtonComponent(
                    style="primary",
                    action=MessageAction(
                        label=category, 
                        text=category
                    ),
                    color="#007bff",
                    height="sm"
                )
            )
        
        bubble = BubbleContainer(
            body=BoxComponent(
                layout="vertical",
                contents=[
                    TextComponent(text="選擇類別", weight="bold", size="xl", align="center"),
                    BoxComponent(
                        layout="vertical",
                        margin="lg",
                        spacing="sm",
                        contents=buttons
                    )
                ]
            )
        )
        
        bubbles.append(bubble)
    
    carousel_message = FlexSendMessage(
        alt_text="類別搜尋",
        contents={
            "type": "carousel",
            "contents": bubbles
        }
    )
    
    line_bot_api.reply_message(reply_token, carousel_message)

def show_preference_settings(reply_token, user_id):
    """顯示偏好設定選單，顯示目前偏好和設定按鈕"""
    user_prefs = get_user_preferences(user_id)
    
    if not user_prefs:
        pref_text = "您尚未設定任何偏好"
    else:
        pref_text = "• " + "\n• ".join(user_prefs)
    
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="您目前的偏好設定", weight="bold", size="xl", margin="md"),
                TextComponent(text=pref_text, wrap=True, margin="md"),
                BoxComponent(
                    layout="vertical",
                    margin="lg",
                    contents=[
                            ButtonComponent(
                            style="primary",
                            action={
                                "type": "postback",
                                "label": "設定偏好",
                                "data": "set_preferences",
                                "displayText": "設定偏好"
                            },
                            color="#1E40AF",  #深藍色
                            margin="md"
                        ),
                        ButtonComponent(
                            style="primary",
                            action=MessageAction(
                                label="全選偏好", 
                                text="全選偏好"
                            ),
                            color="#1E40AF",  # 深藍色
                            margin="md"
                        ),
                        ButtonComponent(
                            style="secondary",
                            action=MessageAction(
                                label="清除偏好", 
                                text="清除偏好"
                            ),
                            color="#60A5FA",  # 淺藍色
                            margin="md"
                        )
                    ]
                )
            ]
        )
    )
    
    message = FlexSendMessage(
        alt_text="偏好設定",
        contents=bubble
    )
    
    line_bot_api.reply_message(reply_token, message)

def show_preference_details(reply_token, user_id):
    """顯示詳細的偏好設定選單"""
    user_prefs = get_user_preferences(user_id)
    
    bubbles = []
    
    # 將類別分組，每組5個
    category_groups = [NEWS_CATEGORIES[i:i+5] for i in range(0, len(NEWS_CATEGORIES), 5)]
    
    for group in category_groups:
        category_buttons = []
        
        for category in group:
            # 檢查該類別是否已被選擇
            is_selected = category in user_prefs
            color = "#1DB446" if is_selected else "#aaaaaa"
            prefix = "✓ " if is_selected else ""
            
            category_buttons.append(
                ButtonComponent(
                    style="primary" if is_selected else "secondary",
                    color=color,
                    action=MessageAction(
                        label=f"{prefix}{category}", 
                        text=category
                    ),
                    height="sm"
                )
            )
        
        # 創建一個氣泡
        bubble = BubbleContainer(
            body=BoxComponent(
                layout="vertical",
                contents=[
                    TextComponent(text="選擇您感興趣的新聞類別", weight="bold", size="md"),
                    TextComponent(text="(點擊可切換選取狀態)", size="xs", color="#aaaaaa", margin="md"),
                    BoxComponent(
                        layout="vertical",
                        margin="lg",
                        spacing="sm",
                        contents=category_buttons
                    )
                ]
            ),
            footer=BoxComponent(
                layout="horizontal",
                spacing="sm",
                contents=[
                    ButtonComponent(
                        style="primary",
                        action=MessageAction(
                            label="全選偏好", 
                            text="全選偏好"
                        )
                    ),
                    ButtonComponent(
                        style="secondary",
                        action=MessageAction(
                            label="清除偏好", 
                            text="清除偏好"
                        )
                    )
                ]
            )
        )
        
        bubbles.append(bubble)
    
    # 將所有氣泡加入Carousel
    carousel_message = FlexSendMessage(
        alt_text="設定新聞偏好",
        contents={
            "type": "carousel",
            "contents": bubbles
        }
    )
    
    line_bot_api.reply_message(reply_token, carousel_message)

def show_help(reply_token):
    """顯示幫助信息"""
    help_text = (
        "📰 新聞偏好機器人使用指南 📰\n\n"
        "【功能說明】\n"
        "本機器人可以幫您追蹤感興趣的新聞類別，設定個人化的新聞偏好。\n\n"
        "【主選單功能】\n"
        "• 類別搜尋：瀏覽所有新聞類別\n"
        "• 偏好設定：查看和修改您的新聞偏好\n"
        "• 幫助：顯示此使用說明\n\n"
        "【指令說明】\n"
        "• 「全選偏好」：選擇所有新聞類別\n"
        "• 「清除偏好」：清除所有新聞偏好\n\n"
        "【操作提示】\n"
        "• 點擊類別名稱可切換該類別的選取狀態\n"
        "• 您可隨時通過底部選單進入各功能\n"
        "• 偏好設定會自動保存在系統中\n\n"
        "如有任何問題，請與我們的客服團隊聯繫。"
    )
    
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=help_text)
    )

def get_user_preferences(user_id):
    """從MongoDB獲取使用者偏好"""
    user = users_collection.find_one({"user_id": user_id})
    if user:
        return user.get("preferences", [])
    return []

def update_user_preferences(user_id, preferences):
    """更新使用者偏好到MongoDB"""
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"preferences": preferences}},
        upsert=True
    )

def toggle_user_preference(user_id, category):
    """切換使用者對特定類別的偏好"""
    user_prefs = get_user_preferences(user_id)
    
    if category in user_prefs:
        user_prefs.remove(category)
    else:
        user_prefs.append(category)
    
    update_user_preferences(user_id, user_prefs)

def create_rich_menu():
    """創建圖文選單"""
    # 使用現有的圖文選單背景圖片
    background_image_path = "richmenu.png"
    
    # 建立圖文選單
    rich_menu_to_create = RichMenu(
        size=RichMenuSize(width=2500, height=843),
        selected=True,  # 預設顯示
        name="新聞機器人選單",  # 選單名稱，管理用，使用者不會看到
        chat_bar_text="開啟選單",  # 選單按鈕文字
        areas=[
            # 左區域：類別搜尋
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=0, width=833, height=843),
                action=MessageAction(label='類別搜尋', text='類別搜尋')
            ),
            # 中區域：偏好設定
            RichMenuArea(
                bounds=RichMenuBounds(x=833, y=0, width=833, height=843),
                action=MessageAction(label='偏好設定', text='偏好設定')
            ),
            # 右區域：幫助
            RichMenuArea(
                bounds=RichMenuBounds(x=1666, y=0, width=834, height=843),
                action=MessageAction(label='幫助', text='幫助')
            )
        ]
    )
    
    # 創建選單並獲取ID
    rich_menu_id = line_bot_api.create_rich_menu(rich_menu_to_create)
    print(f"成功創建圖文選單，ID: {rich_menu_id}")
    
    # 上傳圖文選單圖片
    with open(background_image_path, 'rb') as f:
        line_bot_api.set_rich_menu_image(rich_menu_id, "image/png", f)
    print("成功上傳圖文選單圖片")
    
    # 設定為預設圖文選單
    line_bot_api.set_default_rich_menu(rich_menu_id)
    print("成功設定為預設圖文選單")
    
    return rich_menu_id

def initialize_app():
    """初始化應用，建立圖文選單"""
    try:
        # 檢查是否要刪除現有的圖文選單
        should_delete_existing = False  # 設為 True 如果你想刪除現有選單
        
        if should_delete_existing:
            # 刪除現有的圖文選單
            rich_menu_list = line_bot_api.get_rich_menu_list()
            for rich_menu in rich_menu_list:
                line_bot_api.delete_rich_menu(rich_menu.rich_menu_id)
                print(f"已刪除圖文選單，ID: {rich_menu.rich_menu_id}")
        
        # 創建新的圖文選單
        rich_menu_id = create_rich_menu()
        if rich_menu_id:
            print(f"成功創建並設定圖文選單，ID: {rich_menu_id}")
        else:
            print("無法創建圖文選單")
    except Exception as e:
        print(f"初始化圖文選單時發生錯誤: {e}")

if __name__ == "__main__":
    # 啟動時初始化圖文選單
    initialize_app()
    app.run(host='0.0.0.0', port=5000)