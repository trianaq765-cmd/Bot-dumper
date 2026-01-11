from flask import Flask,jsonify
from threading import Thread
import os,logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)
app=Flask(__name__)
@app.route('/')
def home():return jsonify({"status":"online","message":"Bot is running!"})
@app.route('/health')
def health():return"OK",200
@app.route('/ping')
def ping():return"pong"
def run():
    port=int(os.environ.get('PORT',8080))
    print(f"🌐 Web server starting on port {port}")
    app.run(host='0.0.0.0',port=port,threaded=True)
def keep_alive():
    t=Thread(target=run,daemon=True)
    t.start()
    print("✅ Keep-alive server started")
