import chess
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Initialize a global board state
board = chess.Board()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/move', methods=['POST'])
def make_move():
    global board
    # Get the move data from the frontend (the browser)
    data = request.json
    move_text = data.get("move") # e.g., "e2e4"
    
    # ADD THIS PRINT STATEMENT
    print(f"Attempting move: {move_text} | Current Turn: {'White' if board.turn else 'Black'}")

    try:
        # Create a move object from the text
        move = chess.Move.from_uci(move_text)
        
        # Check if the move is actually allowed by the rules
        if move in board.legal_moves:
            board.push(move)  # Update the Python board
            
            return jsonify({
                "status": "success",
                "fen": board.fen(),        # Send back the new board position
                "check": board.is_check(), # Tell the player if they are in check
                "turn": "white" if board.turn == chess.WHITE else "black"
            })
        else:
            return jsonify({"status": "invalid", "message": "That move is against the rules!"}), 400
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/reset', methods=['POST'])
def reset_board():
    global board
    board = chess.Board()
    return jsonify({"status": "reset", "board": board.fen()})

if __name__ == '__main__':
    app.run(debug=True)