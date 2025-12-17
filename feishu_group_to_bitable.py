# -*- coding: utf-8 -*-
"""
飞书群想法 → AI 日报（多维表格）
适配字段：日期（日期类型）、原始想法（文本）、AI总结（文本）
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
    BJ = timezone(timedelta(hours=8))
    now_bj = datetime.now(BJ)
    today_start_bj = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_bj = now_bj.replace(hour=23, minute=59, second=59, microsecond=999999)

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
        try:
            data = resp.json()
        except json.JSONDecodeError:
            print("⚠️ 飞书消息 API 返回非 JSON 响应")
            print("原始响应:", resp.text[:300])
            break

        if data.get("code") != 0:
            print(f"⚠️ 获取消息失败: {data}")
            break

        items = data["data"].get("items", [])
        for item in items:
            if item["msg_type"] == "text":
                try:
                    text = json.loads(item["body"]["content"])["text"].strip()
                    if text:
                        messages.append(text)
                except Exception as e:
                    continue

        page_token = data["data"].get("page_token")
        if not page_token:
            break

    print(f"📥 共获取到 {len(messages)} 条有效文本消息")
    for i, msg in enumerate(messages[:3], 1):
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
    try:
        result = resp.json()
    except json.JSONDecodeError:
        print("❌ Qwen API 返回非 JSON")
        print("原始响应:", resp.text[:300])
        return "AI 总结生成失败，请检查 DashScope 配额。"

    if resp.status_code != 200 or "output" not in result:
        print(f"❌ Qwen 调用失败: {result}")
        return "AI 总结生成失败，请检查 DashScope 配额或网络。"

    summary = result["output"]["choices"][0]["message"]["content"].strip()
    print(f"🤖 AI 总结: {summary}")
    return summary

def write_to_bitable(token, messages, summary):
    """写入多维表格（字段：日期、原始想法、AI总结）"""
    url = f"{FEISHU_BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records"
    
    # 日期字段：传 YYYY-MM-DD 字符串，飞书会自动转为日期类型
    beijing_date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    
    # 原始想法：合并为多行文本
    raw_ideas = "\n".join(f"- {msg}" for msg in messages) if messages else "无"

    payload = {
        "fields": {
            "日期": beijing_date_str,      # ← 飞书日期类型字段
            "原始想法": raw_ideas,         # ← 文本字段
            "AI总结": summary              # ← 文本字段
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }

    print("📝 准备写入多维表格...")
    print(f"  日期: {beijing_date_str}")
    print(f"  原始想法 (前100字符): {raw_ideas[:100]}{'...' if len(raw_ideas) > 100 else ''}")
    print(f"  AI总结: {summary}")

    resp = requests.post(url, headers=headers, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'))

    print(f"📡 写入请求状态码: {resp.status_code}")
    print(f"📄 Content-Type: {resp.headers.get('content-type', 'unknown')}")

    try:
        result = resp.json()
        print(f"📦 API 响应: {result}")
    except json.JSONDecodeError:
        print("❌ 非 JSON 响应！可能是权限不足或 ID 错误")
        print("原始响应内容（前500字符）:")
        print(resp.text[:500])
        raise Exception("写入失败：飞书 API 返回无效响应")

    if result.get("code") == 0:
        print("✅ 成功写入多维表格！")
        return True
    else:
        print(f"❌ 写入失败: {result}")
        return False

# === 主程序 ===
def main():
    print("🚀 开始执行：飞书群想法 → AI 日报（适配你的表格结构）")
    
    try:
        token = get_tenant_access_token()
        print("🔑 飞书 token 获取成功")

        messages = get_messages(token, FEISHU_CHAT_ID)
        summary = generate_summary(messages)
        
        success = write_to_bitable(token, messages, summary)
        
        if success:
            print("🎉 任务完成！数据已写入多维表格。")
        else:
            print("⚠️ 写入失败，请检查日志和飞书应用权限。")

    except Exception as e:
        print(f"💥 程序异常: {e}")
        raise

if __name__ == "__main__":
    main()
