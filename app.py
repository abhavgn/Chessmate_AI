from flask import Flask, render_template, request, jsonify
import chess
import chess.engine

app = Flask(__name__)

# This is the "Home" page
@app.route('/')
def index():
    return render_template('index.html')

# This will eventually handle the AI "Explain" button
@app.route('/analyze', methods=['POST'])
def analyze():
    # Placeholder for Stockfish + AI logic
    return jsonify({"analysis": "AI Coach is warming up!"})

if __name__ == '__main__':
    app.run(debug=True)