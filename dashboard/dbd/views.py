from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
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
        
        # Проверяем наличие поля marked и добавляем его если нет
        column_names = [col[1] for col in columns]
        if 'marked' not in column_names:
            cursor.execute("ALTER TABLE post_logs ADD COLUMN marked INTEGER DEFAULT 0")
            conn.commit()
            print("Добавлено поле marked в таблицу post_logs")
        
        # Дальнейший код
        today = timezone.now().date()
        
        # Посты за сутки
        posts_today = cursor.execute(
            "SELECT COUNT(*) FROM post_logs WHERE date(created_at) = date('now')"
        ).fetchone()[0]
        
        # Общее количество постов
        total_posts = cursor.execute("SELECT COUNT(*) FROM post_logs").fetchone()[0]
        
        # Помеченные посты
        marked_posts = cursor.execute("SELECT COUNT(*) FROM post_logs WHERE marked = 1").fetchone()[0]
        
        # Успешные посты (не помеченные)
        successful_posts = total_posts - marked_posts
        
        # Статистика по моделям
        model_stats = cursor.execute("""
            SELECT description_model, COUNT(*) as count, 
                   AVG(CASE WHEN marked = 1 THEN 1.0 ELSE 0.0 END) * 100 as fail_rate
            FROM post_logs 
            WHERE description_model IS NOT NULL 
            GROUP BY description_model 
            ORDER BY count DESC LIMIT 5
        """).fetchall()
        
        # Статистика тегов
        tag_stats = cursor.execute("""
            SELECT COUNT(*) as tagged_posts, 
                   AVG(LENGTH(tags)) as avg_tag_length
            FROM post_logs WHERE tags IS NOT NULL AND tags != ''
        """).fetchone()
        
        # Последняя активность
        last_activity = cursor.execute(
            "SELECT created_at FROM post_logs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        
        # Последние посты для маркировки
        recent_posts_raw = cursor.execute("""
            SELECT id, description, tags, created_at, marked
            FROM post_logs 
            ORDER BY created_at DESC 
            LIMIT 20
        """).fetchall()
        
        # Обрабатываем теги для отображения
        recent_posts = []
        for post in recent_posts_raw:
            # Конвертируем теги из формата "tag1|tag2|tag3" в читаемый вид
            tags_display = ""
            if post[2]:  # если теги есть
                if "|" in post[2]:  # новый формат с разделителем |
                    tags_list = [tag.strip() for tag in post[2].split("|") if tag.strip()]
                    tags_display = ", ".join(tags_list[:5])  # показываем первые 5 тегов
                    if len(tags_list) > 5:
                        tags_display += f" (+{len(tags_list) - 5})"
                else:  # старый формат с запятыми
                    tags_display = post[2]
            
            recent_posts.append((post[0], post[1], tags_display, post[3], post[4]))
        
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
            'marked_posts': marked_posts,
            'successful_posts': successful_posts,
            'success_rate': round((successful_posts / total_posts * 100) if total_posts > 0 else 0, 1),
            'db_size': round(get_db_size(), 2),
            'last_activity': last_activity[0] if last_activity else 'Нет данных',
            'chart_labels': json.dumps(chart_labels),
            'chart_data': json.dumps(chart_data),
            'model_stats': model_stats,
            'tagged_posts': tag_stats[0] if tag_stats else 0,
            'avg_tag_length': round(tag_stats[1], 1) if tag_stats and tag_stats[1] else 0,
            'recent_posts': recent_posts,
        }
        
    except sqlite3.OperationalError as e:
        print(f"Ошибка при работе с БД: {e}")
        context = {
            'error': f"Ошибка базы данных: {str(e)}",
            'posts_today': 0,
            'total_posts': 0,
            'marked_posts': 0,
            'successful_posts': 0,
            'success_rate': 0,
            'db_size': round(get_db_size(), 2),
            'last_activity': 'Ошибка БД',
            'chart_labels': json.dumps([]),
            'chart_data': json.dumps([]),
            'model_stats': [],
            'tagged_posts': 0,
            'avg_tag_length': 0,
            'recent_posts': [],
        }
    finally:
        conn.close()
    
    return render(request, "dbd/index.html", context)

@csrf_exempt
@require_POST
def mark_post(request):
    try:
        data = json.loads(request.body)
        post_id = data.get('post_id')
        marked = data.get('marked', 1)

        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "telegram_bot.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("UPDATE post_logs SET marked = ? WHERE id = ?", (marked, post_id))
        conn.commit()
        conn.close()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
