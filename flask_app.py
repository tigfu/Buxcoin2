from flask import Flask, jsonify, request
import os
from datetime import datetime

app = Flask(__name__)

@app.route('/')
def home():
    """Page d'accueil"""
    return jsonify({
        "message": "Bienvenue sur l'API Flask du CryptoBot",
        "timestamp": datetime.now().isoformat(),
        "endpoints": [
            "/",
            "/api/status",
            "/api/info",
            "/api/test",
            "/ping"
        ]
    })

@app.route('/api/status')
def status():
    """Endpoint de statut"""
    return jsonify({
        "status": "online",
        "service": "CryptoBot Flask API",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/info')
def info():
    """Informations sur l'API"""
    return jsonify({
        "name": "CryptoBot Flask API",
        "version": "1.0.0",
        "description": "API Flask pour le bot Discord de cryptomonnaies",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/test', methods=['GET', 'POST'])
def test():
    """Endpoint de test qui accepte GET et POST"""
    if request.method == 'GET':
        return jsonify({
            "method": "GET",
            "message": "Test endpoint fonctionnel",
            "timestamp": datetime.now().isoformat()
        })
    elif request.method == 'POST':
        data = request.get_json() if request.is_json else {}
        return jsonify({
            "method": "POST",
            "message": "Données reçues avec succès",
            "received_data": data,
            "timestamp": datetime.now().isoformat()
        })

@app.route('/ping')
def ping():
    """Endpoint ping simple"""
    return 'Pong!', 200

if __name__ == '__main__':
    # Port dynamique pour Replit
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)