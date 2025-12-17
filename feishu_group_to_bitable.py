import os
import json
import requests
from datetime import datetime, timedelta

# ===== 配置 =====
FEISHU_APP_ID = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]
CHAT_ID = os.environ["FEISHU_CHAT_ID"]
APP_TOKEN = os.environ["BITABLE_APP_TOKEN"]
TABLE_ID = os.environ["BITABLE_TABLE_ID"]
DASHSCOPE_API_KEY = os.environ["DASHSCOPE_API_KEY"]
TZ_OFFSET = int(os.environ.get("TIMEZONE_OFFSET", "8"))

FEISHU_BASE = "https://open.feishu.cn/open-apis"

def get_tenant_access_token():
    url = f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal"
    res = requests.post(url, json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    data = res.json()
    if data.get("code") != 0:
        raise Exception(f"获取 token 失败: {data}")
    return data["tenant_access_token"]

def get_today_start_timestamp():
    """获取今天 00:00:00 的时间戳（毫秒）"""
    now = datetime.utcnow() + timedelta(hours=TZ_OFFSET)
    today_start = datetime(now.year, now.month, now.day)
    return int(today_start.timestamp() * 1000)

def get_messages_since_midnight(chat_id, token):
    """获取从今天 00:00 开始的所有群消息"""
    url = f"{FEISHU_BASE}/im/v1/messages"
    headers = {"Authorization": f"Bearer {token}"}
    
    # 先获取最新消息的时间，作为游标
    params = {
        "container_id_type": "chat",
        "container_id": chat_id,
        "page_size": 1
    }
    res = requests.get(url, headers=headers, params=params)
    items = res.json().get("data", {}).get("items", [])
    if not items:
        return []
    
    latest_msg_time = items[0]["create_time"]  # 毫秒时间戳
    today_start = get_today_start_timestamp()
    
    # 如果最新消息在今天之前，直接返回空
    if latest_msg_time < today_start:
        return []
    
    # 拉取最多 50 条消息
    all_texts = []
    page_token = None
    for _ in range(5):  # 最多 5 页 × 10 = 50 条
        params = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "page_size": 10,
        }
        if page_token:
            params["page_token"] = page_token
        
        res = requests.get(url, headers=headers, params=params)
        data = res.json().get("data", {})
        messages = data.get("items", [])
        
        for msg in messages:
            if msg["create_time"] < today_start:
                return all_texts  # 早于今天，停止
            
            if msg["message_type"] == "text":
                try:
                    content = json.loads(msg["body"]["content"])
                    text = content.get("text", "").strip()
                    if text and not text.startswith("@_user_"):
                        all_texts.append(text)
                except:
                    pass
        
        page_token = data.get("page_token")
        if not page_token:
            break
    
    return list(reversed(all_texts))  # 从早到晚

def call_qwen(text):
    today = (datetime.utcnow() + timedelta(hours=TZ_OFFSET)).strftime("%Y-%m-%d")
    prompt = f"""你是一个高效的知识管理助手。以下是我在【{today}】记录的所有碎片想法，请帮我：
1. 按主题分组（如：工作、项目、灵感、个人事务、待办等）
2. 每组提炼核心内容，去除重复和口语化表达
3. 输出一份简洁清晰的 Markdown 格式日报，不要任何解释性文字。

原始内容如下：
{text}"""
    
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    payload = {
        "model": "qwen-max",
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "parameters": {"result_format": "message"}
    }
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}"}
    response = requests.post(url, json=payload, headers=headers)
    result = response.json()
    if "output" not in result or "choices" not in result["output"]:
        raise Exception(f"Qwen 调用失败: {result}")
    return result["output"]["choices"][0]["message"]["content"]

def save_to_bitable(raw, summary, token):
    today = (datetime.utcnow() + timedelta(hours=TZ_OFFSET)).strftime("%Y-%m-%d")
    url = f"{FEISHU_BASE}/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    
    # 截断超长内容（飞书字段限制）
    payload = {
        "fields": {
            "日期": today,
            "原始想法": (raw[:900] + "...") if len(raw) > 900 else raw,
            "AI总结": (summary[:900] + "...") if len(summary) > 900 else summary,
            "状态": "已完成"
        }
    }
    res = requests.post(url, headers=headers, json=payload)
    if res.status_code != 200:
        raise Exception(f"写入失败: {res.text}")
    return res.json()["data"]["record_id"]

def main():
    print("🔑 获取访问令牌...")
    token = get_tenant_access_token()
    
    print("📥 读取今日群消息...")
    messages = get_messages_since_midnight(CHAT_ID, token)
    
    if not messages:
        print("📭 今日无新想法")
        return
    
    raw_content = "\n".join(messages)
    print(f"✅ 共读取 {len(messages)} 条消息")
    
    print("🧠 调用 Qwen 生成日报...")
    ai_summary = call_qwen(raw_content)
    
    print("💾 写入飞书多维表格...")
    record_id = save_to_bitable(raw_content, ai_summary, token)
    print(f"🎉 成功！记录 ID: {record_id}")

if __name__ == "__main__":
    main()
