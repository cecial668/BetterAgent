import threading
import webbrowser
import uvicorn
from app.api.server import create_app
from app.core.config import HOST, PORT

if __name__ == '__main__':
    app = create_app()
    url = f'http://{HOST}:{PORT}'
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level='info')
