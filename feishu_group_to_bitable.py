
on:
  workflow_dispatch:
  schedule:
    - cron: '0 15 * * *'  # 北京时间 23:00 (UTC+8)

jobs:
  summarize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: pip install requests

      - name: Run Daily Summary
        env:
          FEISHU_APP_ID: ${{ secrets.FEISHU_APP_ID }}
          FEISHU_APP_SECRET: ${{ secrets.FEISHU_APP_SECRET }}
          FEISHU_CHAT_ID: ${{ secrets.FEISHU_CHAT_ID }}
          BITABLE_APP_TOKEN: ${{ secrets.BITABLE_APP_TOKEN }}
          BITABLE_TABLE_ID: ${{ secrets.BITABLE_TABLE_ID }}
          DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}
          TIMEZONE_OFFSET: ${{ secrets.TIMEZONE_OFFSET }}
        run: python feishu_group_to_bitable.py
