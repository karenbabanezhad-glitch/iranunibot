#!/bin/bash
# حذف venv قدیمی و نصب مجدد
rm -rf venv
pip3 install "python-telegram-bot[webhooks]==21.9"
python3 bot.py
