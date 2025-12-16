import os
import json
import requests
import time
import uuid
import urllib3
import re
from datetime import datetime
from mistralai import Mistral


# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
MISTRAL_API_KEY = os.environ.get('MISTRAL_API_KEY') 
MISTRAL_AGENT_ID = os.environ.get('MISTRAL_AGENT_ID') 

# --- Supabase Helpers ---
def sb_request(method, endpoint, data=None, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    try:
        if method == 'GET':
            r = requests.get(url, headers=headers, params=params)
        elif method == 'POST':
            r = requests.post(url, headers=headers, json=data)
        elif method == 'PATCH':
            r = requests.patch(url, headers=headers, json=data, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Supabase Error ({method} {endpoint}): {e}")
        return None

def evaluate_answer(task_text, key_text, user_answer, db_max_score):

    
   
    client = Mistral(api_key=MISTRAL_API_KEY)
    
    prompt=f"Задание: {task_text} Эталонный ответ (для сверки смысла, не слов): {key_text}. Ответ ученика: {user_answer}. Максимальный балл: {db_max_score}"
    response = client.beta.conversations.start(
        agent_id=MISTRAL_AGENT_ID,
        inputs=prompt,
    )

    return response.outputs[0].content


# --- Telegram Helper ---
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Telegram Error: {e}")

# --- MAIN HANDLER ---
def handler(event, context):
    print("Worker started...")
    
    # 1. Fetch pending tasks (LIMIT 5 to avoid timeouts per execution)
    pending_items = sb_request('GET', 'processing_queue', params={
        "select": "*",
        "status": "eq.pending",
        "limit": "5",
        "order": "created_at.asc"
    })
    
    if not pending_items:
        print("No pending tasks found.")
        return {"statusCode": 200, "body": "Idle"}
    
    print(f"Found {len(pending_items)} tasks.")

    for item in pending_items:
        queue_id = item['id']
        user_id = item['user_id']
        chat_id = item['chat_id']
        task_id = item['task_id']
        user_answer = item['user_answer_text']
        
        print(f"Processing queue_id {queue_id}...")
        
        # 2. Get Task Details (Question & Key)
        tasks = sb_request('GET', 'tasks', params={"id": f"eq.{task_id}"})
        if not tasks:
            print(f"Task {task_id} not found!")
            sb_request('PATCH', 'processing_queue', data={"status": "error", "error_message": "Task not found"}, params={"id": f"eq.{queue_id}"})
            continue
            
        task = tasks[0]
        db_max_score = task.get('max_score', 2)
        
        # 3. Call LLM
        llm_result = evaluate_answer(task['text'], task['answer_key_text'], user_answer, db_max_score)
        
        if not llm_result:
            # Maybe we should retry later? or mark error
            print("LLM failed.")
            continue

        # 4. Parse Score 
        # Matches: "Баллы: 3", "**Баллы**: 3", "Баллы - 3", "Баллы 3"
        score_match = re.search(r"Баллы\D*(\d+([.,]\d+)?)", llm_result, re.IGNORECASE)
        
        if score_match:
            score_str = score_match.group(1).replace(',', '.') # Handle "3,5"
            score = float(score_str)
        else:
            print(f"⚠️ Warning: Could not parse score from: {llm_result}") 
            score = 0.0
        
        # 5. Save to Attempts Table
        attempt_data = {
            "user_id": user_id,
            "task_id": task_id,
            "user_answer_text": user_answer,
            "chat_response": {"raw": llm_result},
            "score": score,       # Parsed from LLM
            "max_score": db_max_score, # From our Database
            "comment": llm_result
        }
        sb_request('POST', 'attempts', data=attempt_data)
        
        # 6. Update Queue Status
        sb_request('PATCH', 'processing_queue', 
                   data={"status": "processed", "processed_at": datetime.utcnow().isoformat()}, 
                   params={"id": f"eq.{queue_id}"})
        
        result_text = f"✅ *Проверка завершена!*\n\n{llm_result}"
        send_telegram_message(chat_id, result_text)
        
    return {
        "statusCode": 200,
        "body": f"Processed {len(pending_items)} tasks"
    }
