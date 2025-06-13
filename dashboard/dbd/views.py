from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from datetime import timedelta
import os
import sqlite3
import json

def get_db_size():
    # Поднимаемся на два уровня выше от папки dbd
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "telegram_bot.db")
    return os.path.getsize(db_path) / (1024 * 1024)  # Размер в МБ

def index(request):
    # Подключение к БД в корневой папке TgPoster
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "telegram_bot.db")
    print(f"Путь к БД: {db_path}")
    print(f"Файл существует: {os.path.exists(db_path)}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Проверяем существующие таблицы
    tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"Существующие таблицы: {tables}")
    
    try:
        # Проверяем структуру таблицы post_logs
        cursor.execute("PRAGMA table_info(post_logs)")
        columns = cursor.fetchall()
        print(f"Структура post_logs: {columns}")
        
        # Дальнейший код
        today = timezone.now().date()
        
        # Посты за сутки
        posts_today = cursor.execute(
            "SELECT COUNT(*) FROM post_logs WHERE date(created_at) = date('now')"
        ).fetchone()[0]
        
        # Общее количество постов
        total_posts = cursor.execute("SELECT COUNT(*) FROM post_logs").fetchone()[0]
        
        # Последняя активность
        last_activity = cursor.execute(
            "SELECT created_at FROM post_logs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        
        # Данные для графика (последние 7 дней)
        activity_data = cursor.execute("""
            SELECT date(created_at) as date, COUNT(*) as count 
            FROM post_logs 
            WHERE created_at >= date('now', '-7 days')
            GROUP BY date(created_at)
            ORDER BY date
        """).fetchall()
        
        chart_labels = [str(row[0]) for row in activity_data]
        chart_data = [row[1] for row in activity_data]
        
        context = {
            'posts_today': posts_today,
            'total_posts': total_posts,
            'db_size': round(get_db_size(), 2),
            'last_activity': last_activity[0] if last_activity else 'Нет данных',
            'chart_labels': json.dumps(chart_labels),
            'chart_data': json.dumps(chart_data),
        }
        
    except sqlite3.OperationalError as e:
        print(f"Ошибка при работе с БД: {e}")
        context = {
            'error': f"Ошибка базы данных: {str(e)}",
            'posts_today': 0,
            'total_posts': 0,
            'db_size': round(get_db_size(), 2),
            'last_activity': 'Ошибка БД',
            'chart_labels': json.dumps([]),
            'chart_data': json.dumps([]),
        }
    finally:
        conn.close()
    
    return render(request, "dbd/index.html", context)
