
import json
import os
import requests
import time
import uuid
import urllib3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import random
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========Configuration =============
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')




# ============= SUPABASE API =============
def supabase_request(method: str, table: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Any:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }
    
    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=10)
        elif method == 'POST':
            response = requests.post(url, headers=headers, json=data, timeout=10)
        elif method == 'PATCH':
            response = requests.patch(url, headers=headers, json=data, params=params, timeout=10)
        elif method == 'DELETE':  # <--- ADD THIS BLOCK
            response = requests.delete(url, headers=headers, params=params, timeout=10)
        else:
            raise ValueError(f"Неподдерживаемый метод: {method}")
        
        #DELETE might return 204 No Content, which has no JSON.
        if response.status_code == 204:
            return None
            
        response.raise_for_status()
        return response.json()
        
    except Exception as e:
        print(f"❌ Ошибка Supabase запроса: {method} {url} with params {params} -> {e}")
        return None

# ============= Task helper =============
def get_random_task(user_id: int, category: Optional[str] = None) -> Optional[Dict]:
   #Receives a random task that has not yet been solved by a maximum score.
    try:
        # 1. Get solved tasks id
        attempts_params = {'user_id': f'eq.{user_id}'}
        attempts = supabase_request('GET', 'attempts', params=attempts_params)
        
        solved_task_ids = set()
        if attempts:
            for attempt in attempts:
                
                score = attempt.get('score')
                max_score = attempt.get('max_score')
                
                score_val = float(score) if score is not None else 0.0
                max_score_val = float(max_score) if max_score is not None else 0.0
                
                if max_score_val > 0 and score_val >= (max_score_val - 0.1):
                    solved_task_ids.add(attempt['task_id'])

        # 2. Get all tasks with category
        task_params = {}
        if category and category != 'all':
            task_params['category'] = f'eq.{category}'
            
        tasks = supabase_request('GET', 'tasks', params=task_params)
        
        if not tasks: 
            return None

        # 3. Filter tasks
        available_tasks = [t for t in tasks if t['id'] not in solved_task_ids]
        
        if not available_tasks: 
            return None
        
        return random.choice(available_tasks)
    except Exception as e:
        print(f"❌ Error getting task: {e}")
        import traceback
        traceback.print_exc()
        return None


def add_to_processing_queue(chat_id: int, user_id: int, task_id: int, user_answer: str):
    data = {
        'chat_id': chat_id,
        'user_id': user_id,
        'task_id': task_id,
        'user_answer_text': user_answer,
        'status': 'pending',
        'created_at': datetime.utcnow().isoformat()
    }
    
    try:
        result = supabase_request('POST', 'processing_queue', data=data)
        print(f"✅ Задача добавлена в очередь (queue_id: {result[0]['id']})")
        return result[0]
    except Exception as e:
        print(f"❌ Ошибка добавления в очередь: {e}")
        return None

# ============= TELEGRAM API =============
def send_telegram_message(chat_id: int, text: str, reply_markup: Optional[Dict] = None):
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    
    if reply_markup:
        payload['reply_markup'] = reply_markup
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Ошибка отправки сообщения в Telegram: {e}")
        raise

# --- Helper to get categories ---
def get_categories() -> list:
    try:
        response = supabase_request('GET', 'tasks', params={'select': 'category'})
        if not response: return []
        
        categories = sorted(list(set(r['category'] for r in response if r.get('category'))))
        return categories
    except Exception as e:
        print(f"Error fetching categories: {e}")
        return []

# ---Keyboard Generators ---
def get_main_keyboard():
    return {
        'keyboard': [
            [{'text': '📝 Получить задание'}],
            [{'text': '📊 Моя статистика'}, {'text': '🔄 Сбросить рейтинг'}]
        ],
        'resize_keyboard': True
    }
def get_categories_keyboard(categories):
    keyboard = []
    # Add "All Categories" button first
    keyboard.append([{'text': '🎲 Все категории'}])
    
    # Add categories in rows of 2
    row = []
    for cat in categories:
        row.append({'text': f"📂 {cat}"})
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    # Add "Back" button
    keyboard.append([{'text': '⬅️ Назад в меню'}])
    
    return {
        'keyboard': keyboard,
        'resize_keyboard': True
    }
# ============= ЛОГИКА ПОЛЬЗОВАТЕЛЕЙ =============

def get_or_create_user(user_id: int, username: str = None) -> Dict:
    """Checks the user's rights and balance.
    If there is no user, it creates one with default settings.
    """
    try:
        users = supabase_request('GET', 'users', params={'user_id': f'eq.{user_id}'})
        
        if users and len(users) > 0:
            return users[0]
        
        new_user = {
            'user_id': user_id,
            'username': username,
            'is_allowed': True, 
            'tasks_left': 100
        }
        created_user = supabase_request('POST', 'users', data=new_user)
        if created_user:
            return created_user[0]
        return new_user 
        
    except Exception as e:
        print(f"❌ Ошибка при работе с пользователем: {e}")
        return None

def decrease_user_tasks(user_id: int):
    try:
        user = supabase_request('GET', 'users', params={'user_id': f'eq.{user_id}'})
        if user:
            current = user[0].get('tasks_left', 0)
            if current > 0:
                supabase_request('PATCH', 'users', 
                               params={'user_id': f'eq.{user_id}'}, 
                               data={'tasks_left': current - 1})
    except Exception as e:
        print(f"❌ Ошибка списания баланса: {e}")

# ============= User states =============

def set_user_state(user_id: int, state: str, data: Optional[Dict] = None):
    payload = {
        'user_id': user_id,
        'state': state,
        'data': data or {},
        'updated_at': datetime.utcnow().isoformat()
    }
    
    
    try:
        existing = supabase_request('GET', 'user_states', params={'user_id': f'eq.{user_id}'})
        
        if existing:
            supabase_request('PATCH', 'user_states', 
                           params={'user_id': f'eq.{user_id}'}, 
                           data=payload)
        else:
            supabase_request('POST', 'user_states', data=payload)
            
    except Exception as e:
        print(f"❌ Ошибка сохранения состояния: {e}")


def get_user_state(user_id: int) -> Optional[Dict]:
    try:
        response = supabase_request('GET', 'user_states', params={'user_id': f'eq.{user_id}'})
        
        if not response:
            return None
            
        state_record = response[0]
        
        updated_at = datetime.fromisoformat(state_record['updated_at'].replace('Z', '+00:00'))
        if (datetime.utcnow().replace(tzinfo=None) - updated_at.replace(tzinfo=None)) > timedelta(hours=24):
            clear_user_state(user_id)
            return None
            
        return state_record
        
    except Exception as e:
        print(f"❌ Ошибка получения состояния: {e}")
        return None


def clear_user_state(user_id: int):
    try:
        supabase_request('DELETE', 'user_states', params={'user_id': f'eq.{user_id}'})
    except Exception as e:
        print(f"❌ Ошибка очистки состояния: {e}")


# ============= Commands handler =============
def handle_start(chat_id: int, user_id: int):

    
    welcome_text = """👋 <b>Привет! Я бот для подготовки к олимпиадам!</b>

Я помогу тебе тренироваться в решении олимпиадных заданий с развернутыми ответами.

<b>Как это работает:</b>
1️⃣ Нажми кнопку "📝 Получить задание"
2️⃣ Прочитай задание и напиши развернутый ответ
3️⃣ Я проверю твой ответ с помощью искусственного интеллекта
4️⃣ Ты получишь баллы и комментарии по своему ответу

Готов начать? Жми на кнопку! 🚀"""
    
    send_telegram_message(chat_id, welcome_text, reply_markup=get_main_keyboard())

def handle_get_task_menu(chat_id: int, user_id: int):
    """Shows the category selection menu"""
    categories = get_categories()
    if not categories:
        handle_get_task_execution(chat_id, user_id, category=None)
        return

    msg = "Выберите категорию заданий:"
    send_telegram_message(chat_id, msg, reply_markup=get_categories_keyboard(categories))
    # Set state to expect category selection
    set_user_state(user_id, 'waiting_for_category')

def handle_get_task_execution(chat_id: int, user_id: int, category: Optional[str]):

    # --- 💰 Balance check :)
    user_db = get_or_create_user(user_id)
    tasks_left = user_db.get('tasks_left', 0)
    
    if tasks_left <= 0:
        send_telegram_message(
            chat_id, 
            "💳 <b>Доступ запрещен.</b>\n\n"
            "На вашем балансе 0 попыток.",
            reply_markup=get_main_keyboard()
        )
        clear_user_state(user_id)
        return
    task = get_random_task(user_id, category)
    
    if not task:
        msg = "🎉 Вы решили все задачи в этой категории на максимум!"
        if category:
            msg += "\nПопробуйте другую категорию или сбросьте рейтинг."
        send_telegram_message(chat_id, msg, reply_markup=get_main_keyboard())
        clear_user_state(user_id) # Reset state so they aren't stuck
        return

   
    set_user_state(user_id, 'waiting_for_answer', {'task': task})
    
    task_text = f"📝 Задание ({task.get('category', 'Общее')}):\n{task['text']}\n\nНапиши свой развернутый ответ."
    send_telegram_message(chat_id, task_text, reply_markup=get_main_keyboard()) 





def handle_answer(chat_id: int, user_id: int, answer_text: str):
    state = get_user_state(user_id)
    if not state or state['state'] != 'waiting_for_answer':
        send_telegram_message(
            chat_id,
            "❓ Сначала получи задание, нажав кнопку '📝 Получить задание'",
            reply_markup=get_main_keyboard()
        )
        return

    
    user_db = get_or_create_user(user_id)
    tasks_left = user_db.get('tasks_left', 0)
    
    if tasks_left <= 0:
        send_telegram_message(
            chat_id,
            "💳 <b>Закончились доступные проверки.</b>\n\n"
            "Ваша подписка исчерпана. Пожалуйста, пополните баланс, чтобы продолжить обучение.",
            reply_markup=get_main_keyboard()
        )
        clear_user_state(user_id) 
        return

    task = state['data']['task']
    
    queue_item = add_to_processing_queue(
        chat_id=chat_id,
        user_id=user_id,
        task_id=task['id'],
        user_answer=answer_text
    )
    
    if queue_item:
        # --- 📉 Decrease balance ---
        decrease_user_tasks(user_id)
        # -------------------
        
        send_telegram_message(
            chat_id,
            f"⏳ Твой ответ принят! Осталось попыток: <b>{tasks_left - 1}</b>.\n"
            "Проверяю... Результат придёт в течение пары минут."
        )
    else:
        send_telegram_message(
            chat_id,
            "❌ Произошла ошибка. Попробуй еще раз!",
            reply_markup=get_main_keyboard()
        )
    
    clear_user_state(user_id)

def handle_statistics(chat_id: int, user_id: int):
    try:
        attempts = supabase_request('GET', 'attempts', params={'user_id': f'eq.{user_id}'})
        
        if not attempts or len(attempts) == 0:
            send_telegram_message(
                chat_id,
                "📊 У тебя пока нет решенных заданий. Начни тренировку!",
                reply_markup=get_main_keyboard()
            )
            return
        
        total_attempts = len(attempts)
        scores = [round(a['score']/a['max_score']*100) for a in attempts if a.get('score') is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        best_score = max(scores) if scores else 0
        
        stats_text = f"📊 <b>Твоя статистика:</b>\n📝 Попыток решений: {total_attempts}\n⭐️ Средний процент решения: {avg_score}%\n🎯 Лучший результат: {best_score}%\n\nПродолжай в том же духе! 🚀"
        
        send_telegram_message(chat_id, stats_text, reply_markup=get_main_keyboard())
        
    except Exception as e:
        print(f"❌ Ошибка получения статистики: {e}")
        send_telegram_message(
            chat_id,
            "❌ Не удалось получить статистику. Попробуй позже.",
            reply_markup=get_main_keyboard()
        )

# ============= Main handler=============
def process_update(update: Dict):
    if 'message' not in update: return
    message = update['message']
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    username = message['from'].get('username')
    
    if 'text' not in message: return
    text = message['text']

    # --- 🛡️ Acces check ---
    user_db = get_or_create_user(user_id, username)
    
    if not user_db or not user_db.get('is_allowed'):
        send_telegram_message(
            chat_id, 
            "⛔️ <b>Доступ ограничен.</b>\n\nЭтот бот работает в закрытом режиме. "
            "Свяжитесь с администратором для получения доступа."
        )
        return


    if text == '/start':
        handle_start(chat_id, user_id)
        return
    elif text == '📝 Получить задание':
        handle_get_task_menu(chat_id, user_id)
        return
    elif text == '📊 Моя статистика':
        handle_statistics(chat_id, user_id)
        return
    elif text == '🔄 Сбросить рейтинг':
        handle_reset_statistics(chat_id, user_id)
        return
    elif text == '⬅️ Назад в меню':
        send_telegram_message(chat_id, "Главное меню", reply_markup=get_main_keyboard())
        clear_user_state(user_id)
        return

    state = get_user_state(user_id)
    
    if state:
        if state['state'] == 'waiting_for_category':
            if text == '🎲 Все категории':
                handle_get_task_execution(chat_id, user_id, category='all')
            elif text.startswith('📂 '):
                category = text.replace('📂 ', '')
                handle_get_task_execution(chat_id, user_id, category=category)
            else:
                send_telegram_message(chat_id, "Пожалуйста, выберите категорию из меню.")
            return

        elif state['state'] == 'waiting_for_answer':
            handle_answer(chat_id, user_id, text)
            return

   
    send_telegram_message(chat_id, "Используйте меню для управления.", reply_markup=get_main_keyboard())

def handle_reset_statistics(chat_id: int, user_id: int):
    try:
        attempts = supabase_request('GET', 'attempts', params={'user_id': f'eq.{user_id}', 'select': 'id', 'limit': '1'})
        
        if not attempts:
             send_telegram_message(chat_id, "У вас нет решенных задач для сброса.", reply_markup=get_main_keyboard())
             return

        delete_params = {'user_id': f'eq.{user_id}'}
        supabase_request('DELETE', 'attempts', params=delete_params)
        
        send_telegram_message(chat_id, "🔄 Статистика полностью сброшена. Все задачи снова доступны!", reply_markup=get_main_keyboard())
        
    except Exception as e:
        print(f"Reset error: {e}")
        send_telegram_message(chat_id, "Ошибка при сбросе статистики.")

# ============= CLOUD FUNCTION HANDLER =============
def handler(event, context):

    try:
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})
        
        if body:
            process_update(body)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'status': 'ok'})
        }
    
    except Exception as e:
        print(f"❌ Критическая ошибка в handler: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
