# -*- coding: utf-8 -*-
"""
飞书群想法 → AI 日报（多维表格）
功能：每天自动读取指定群聊的文本消息，用 Qwen 生成总结，并写入多维表格。
"""

import os
import requests
import json
from datetime import datetime, timezone, timedelta

# === 从环境变量读取配置 ===
FEISHU_APP_ID = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]
FEISHU_CHAT_ID = os.environ["FEISHU_CHAT_ID"]
BITABLE_APP_TOKEN = os.environ["BITABLE_APP_TOKEN"]
BITABLE_TABLE_ID = os.environ["BITABLE_TABLE_ID"]
DASHSCOPE_API_KEY = os.environ["DASHSCOPE_API_KEY"]

FEISHU_BASE = "https://open.feishu.cn/open-apis"
DASHSCOPE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"

# === 工具函数 ===
def get_tenant_access_token():
    """获取飞书 tenant_access_token"""
    url = f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal"
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    resp = requests.post(url, json=payload)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"❌ 获取飞书 token 失败: {data}")
    return data["tenant_access_token"]

def get_messages(token, chat_id):
    """获取群聊中今天（北京时间）的所有文本消息"""
    # 定义北京时间
    BJ = timezone(timedelta(hours=8))
    now_bj = datetime.now(BJ)
    today_start_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_bj = now_bj.replace(hour=23, minute=59, second=59, microsecond=999999)

    # 转为 UTC 毫秒时间戳（飞书 API 要求字符串）
    start_time = str(int(today_start_bj.timestamp() * 1000))
    end_time = str(int(today_end_bj.timestamp() * 1000))

    print(f"🕒 查询时间范围（北京时间）: {today_start_bj.strftime('%Y-%m-%d %H:%M:%S')} ~ {today_end_bj.strftime('%Y-%m-%d %H:%M:%S')}")

    messages = []
    page_token = None

    while True:
        params = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "start_time": start_time,
            "end_time": end_time,
            "page_size": 50,
        }
        if page_token:
            params["page_token"] = page_token

        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(f"{FEISHU_BASE}/im/v1/messages", headers=headers, params=params)
        data = resp.json()

        if data["code"] != 0:
            print(f"⚠️ 获取消息失败: {data}")
            break

        items = data["data"].get("items", [])
        for item in items:
            if item["msg_type"] == "text":
                try:
                    text = json.loads(item["body"]["content"])["text"].strip()
                    if text:  # 忽略空消息
                        messages.append(text)
                except:
                    continue  # 跳过解析失败的消息

        # 分页
        page_token = data["data"].get("page_token")
        if not page_token:
            break

    print(f"📥 共获取到 {len(messages)} 条有效文本消息")
    for i, msg in enumerate(messages[:3], 1):  # 只打印前3条
        print(f"  [{i}] {msg[:60]}{'...' if len(msg) > 60 else ''}")
    if len(messages) > 3:
        print(f"  ... 还有 {len(messages) - 3} 条")

    return messages

def generate_summary(messages):
    """调用 Qwen 生成总结"""
    if not messages:
        return "今日无新想法。"

    prompt = (
        "你是一位高效的信息整理助手。请将以下用户的想法/笔记/待办事项，"
        "整理成一段简洁、有条理的中文日报总结（100字以内）：\n\n"
        + "\n".join(f"- {msg}" for msg in messages)
    )

    payload = {
        "model": "qwen-max",
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "parameters": {"max_tokens": 300}
    }

    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }

    resp = requests.post(DASHSCOPE_URL, headers=headers, json=payload)
    result = resp.json()

    if resp.status_code != 200 or "output" not in result:
        print(f"❌ Qwen 调用失败: {result}")
        return "AI 总结生成失败，请检查 DashScope 配额或网络。"

    summary = result["output"]["choices"][0]["message"]["content"].strip()
    print(f"🤖 AI 总结: {summary}")
    return summary

def write_to_bitable(token, summary):
    """写入多维表格"""
    url = f"{FEISHU_BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records"
    
    # ⚠️ 注意：字段名必须和你的多维表格「字段名」完全一致！
    # 假设你的表格有两列：「日期」、「内容」
    beijing_date = (datetime.now(timezone(timedelta(hours=8)))).strftime("%Y-%m-%d")
    
    payload = {
        "fields": {
            "日期": beijing_date,
            "内容": summary
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    result = resp.json()

    if result.get("code") == 0:
        print("✅ 成功写入多维表格！")
        return True
    else:
        print(f"❌ 写入表格失败: {result}")
        return False

# === 主程序 ===
def main():
    print("🚀 开始执行：飞书群想法 → AI 日报")
    
    try:
        # 1. 获取飞书 token
        token = get_tenant_access_token()
        print("🔑 飞书 token 获取成功")

        # 2. 读取消息
        messages = get_messages(token, FEISHU_CHAT_ID)
        
        # 3. 生成总结
        summary = generate_summary(messages)
        
        # 4. 写入表格
        success = write_to_bitable(token, summary)
        
        if success:
            print("🎉 任务完成！明日再见~")
        else:
            print("⚠️ 任务部分失败，请检查日志")

    except Exception as e:
        print(f"💥 程序异常: {e}")
        raise

if __name__ == "__main__":
    main()
