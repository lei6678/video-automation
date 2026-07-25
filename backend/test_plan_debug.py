import asyncio, os, sys, json, httpx
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

deepseek_key = os.getenv('DEEPSEEK_API_KEY', '')
rewritten = open('data/tasks/4/rewritten.txt', 'r', encoding='utf-8').read()

async def main():
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
        resp = await http.post(
            'https://api.deepseek.com/v1/chat/completions',
            json={
                'model': 'deepseek-v4-pro',
                'messages': [
                    {'role': 'system', 'content': 'Say hello in JSON: {"greeting": "hello"}'},
                    {'role': 'user', 'content': 'respond'},
                ],
                'temperature': 0.7,
                'max_tokens': 100,
            },
            headers={'Authorization': f'Bearer {deepseek_key}', 'Content-Type': 'application/json'},
        )
        print(f'Status: {resp.status_code}')
        data = resp.json()
        choice = data['choices'][0]
        print(f'Finish reason: {choice.get("finish_reason")}')
        msg = choice.get('message', {})
        print(f'Message keys: {list(msg.keys())}')
        print(f'Content repr: {repr(msg.get("content"))}')
        print(f'Raw choice: {json.dumps(choice, ensure_ascii=False)[:500]}')

asyncio.run(main())
