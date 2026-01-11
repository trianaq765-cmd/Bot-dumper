from flask import Flask
from threading import Thread
import os
app=Flask(__name__)
@app.route('/')
def h():return'{"status":"ok"}'
@app.route('/health')
def hp():return'OK'
def run():app.run(host='0.0.0.0',port=int(os.environ.get('PORT',8080)),threaded=True,use_reloader=False)
def keep_alive():Thread(target=run,daemon=True).start();print("✅ Server ready")
