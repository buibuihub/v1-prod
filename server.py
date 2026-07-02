from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote
import json
import mimetypes
import os
import urllib.request
import urllib.error
from pathlib import Path
from ytmusicapi import YTMusic

yt = YTMusic()
ROOT_DIR = Path(__file__).resolve().parent
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'


def fallback_reply(prompt: str) -> str:
    prompt_lower = prompt.lower()
    if 'hello' in prompt_lower or 'hi' in prompt_lower:
        return "Hello! I’m Nova. I can help with study plans, coding, weather, or your workspace."
    if 'code' in prompt_lower or 'python' in prompt_lower or 'html' in prompt_lower or 'javascript' in prompt_lower:
        return "I can help you write or debug code. Share the error or the goal and I’ll guide you through it."
    if 'study' in prompt_lower or 'learn' in prompt_lower:
        return "A great study plan is to break the topic into 3 small parts, practice one, then review what you missed."
    if 'weather' in prompt_lower:
        return "I can help you check the weather if you tell me the city name."
    return f"I’m Nova, and I can help with your project. You asked: {prompt}"


def groq_reply(prompt: str) -> str:
    api_key = os.getenv('GROQ_API_KEY') or GROQ_API_KEY
    if not api_key:
        return fallback_reply(prompt)

    payload = {
        'model': 'llama-3.3-70b-versatile',
        'messages': [
            {'role': 'system', 'content': 'You are Nova, a concise helpful assistant for a student developer.'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.6,
        'max_tokens': 500
    }

    req = urllib.request.Request(
        'https://api.groq.com/openai/v1/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'User-Agent': USER_AGENT,
            'Accept': 'application/json'
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data['choices'][0]['message']['content']
    except urllib.error.HTTPError as err:
        try:
            body = err.read().decode('utf-8', errors='replace')
            print('Groq HTTP error:', err.code, err.reason, body)
        except Exception:
            print('Groq HTTP error:', err)
        return fallback_reply(prompt)
    except Exception as exc:
        print('Groq request failed:', exc)
        return fallback_reply(prompt)

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

        def do_HEAD(self):
        # Respond with a 200 OK for the health check, without a body
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
    
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path in ('/', '/index.html'):
            self.serve_static_file('index.html')
            return

        if parsed.path == '/health':
            self.send_json({'status': 'ok'})
            return

        if parsed.path == '/search':
            query = parse_qs(parsed.query).get('q', [''])[0].strip()
            if not query:
                self.send_json({'error': 'Missing query'}, status=400)
                return

            try:
                results = yt.search(query, filter='songs', limit=5)
                songs = []
                for r in results:
                    artists_list = r.get('artists', [])
                    artist_name = artists_list[0].get('name', '') if artists_list else ''
                    thumbnails = r.get('thumbnails', [])
                    thumb_url = thumbnails[0].get('url', '') if thumbnails else ''
                    songs.append({
                        'videoId': r.get('videoId'),
                        'title': r.get('title', ''),
                        'artist': artist_name,
                        'duration': r.get('duration', ''),
                        'thumbnail': thumb_url
                    })
                self.send_json({'songs': songs})
            except Exception as exc:
                self.send_json({'error': str(exc)}, status=500)
            return

        if parsed.path == '/ai':
            prompt = parse_qs(parsed.query).get('prompt', [''])[0].strip()
            if not prompt:
                self.send_json({'error': 'Missing prompt'}, status=400)
                return

            self.send_json({'reply': groq_reply(prompt)})
            return

        if parsed.path == '/weather':
            city = parse_qs(parsed.query).get('city', [''])[0].strip()
            if not city:
                self.send_json({'error': 'Missing city'}, status=400)
                return

            self.send_json(weather_reply(city))
            return

        if parsed.path.startswith('/'):
            static_path = parsed.path.lstrip('/')
            if static_path and '..' not in Path(static_path).parts:
                self.serve_static_file(static_path)
                return

        self.send_json({'error': 'Not found'}, status=404)

    def do_POST(self):
        print('Received POST', self.path)
        parsed = urlparse(self.path)
        if parsed.path != '/ai':
            self.send_json({'error': 'Not found'}, status=404)
            return

        content_length = int(self.headers.get('Content-Length', 0))
        try:
            raw_body = self.rfile.read(content_length).decode('utf-8')
            body = json.loads(raw_body)
            prompt = body.get('prompt', '').strip()
        except Exception:
            self.send_json({'error': 'Invalid JSON body'}, status=400)
            return

        if not prompt:
            self.send_json({'error': 'Missing prompt'}, status=400)
            return

        self.send_json({'reply': groq_reply(prompt)})
        return

    def serve_static_file(self, relative_path: str) -> None:
        safe_path = Path(relative_path)
        if safe_path.is_absolute() or '..' in safe_path.parts:
            self.send_json({'error': 'Invalid path'}, status=400)
            return

        file_path = (ROOT_DIR / safe_path).resolve()
        try:
            file_path.relative_to(ROOT_DIR)
        except ValueError:
            self.send_json({'error': 'Invalid path'}, status=400)
            return

        if not file_path.exists() or not file_path.is_file():
            self.send_json({'error': 'Not found'}, status=404)
            return

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = 'application/octet-stream'

        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def weather_reply(city: str) -> dict:
    api_key = os.getenv('OPENWEATHER_API_KEY') or OPENWEATHER_API_KEY
    if not api_key:
        return {'error': 'Weather API key missing'}

    url = (
        'https://api.openweathermap.org/data/2.5/weather'
        f'?q={quote(city)}&appid={api_key}&units=metric'
    )

    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode('utf-8'))
            return {
                'city': data.get('name', city),
                'country': data.get('sys', {}).get('country', ''),
                'temperature': round(data.get('main', {}).get('temp', 0)),
                'description': data.get('weather', [{}])[0].get('description', 'clear sky'),
                'humidity': data.get('main', {}).get('humidity', 0),
                'wind': round(data.get('wind', {}).get('speed', 0), 1),
                'feels_like': round(data.get('main', {}).get('feels_like', 0)),
            }
    except Exception as exc:
        print('Weather request failed:', exc)
        return {'error': 'Weather unavailable'}


def run_test(prompt: str = 'hi') -> None:
    print('Running local Nova AI test...')
    reply = groq_reply(prompt)
    print('Prompt:', prompt)
    print('Reply:', reply)


def run_server() -> None:
    server = ThreadingHTTPServer(('127.0.0.1', 8000), Handler)
    print('Listening on http://127.0.0.1:8000')
    server.serve_forever()


if __name__ == '__main__':
    import sys
    if '--test' in sys.argv:
        prompt = ' '.join(arg for arg in sys.argv[1:] if arg != '--test') or 'hi'
        run_test(prompt)
    else:
        run_server()
