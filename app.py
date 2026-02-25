from flask import Flask, render_template, request, jsonify

import chess

import chess.engine



app = Flask(__name__)



# Initialize a global board state

board = chess.Board()



@app.route('/')

def index():

    return render_template('index.html')



# This path tells Python exactly where your "brain" file is

engine_path = "./engines/stockfish"



def get_evaluation(fen):
    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        temp_board = chess.Board(fen)
        info = engine.analyse(temp_board, chess.engine.Limit(time=0.1))
        score = info["score"].white()
        
        # This prevents the "NoneType" error when there is a mate
        if score.is_mate():
            mate_val = score.mate()
            return f"M{mate_val}" if mate_val is not None else "M"
        
        # Get the numerical score safely
        val = score.score()
        return val / 100.0 if val is not None else 0.0


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

           

            # --- ADD THIS LINE TO GET THE EVAL ---

            current_eval = get_evaluation(board.fen())

           

            return jsonify({

                "status": "success",

                "fen": board.fen(),

                "check": board.is_check(),

                "turn": "white" if board.turn == chess.WHITE else "black",

                "evaluation": current_eval  # <--- Send the score to the frontend!

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



@app.route("/engine_move", methods=["POST"])
def engine_move():
    global board
    data = request.json
    
    try:
        elo_rating = int(data.get("level", 200))
    except (TypeError, ValueError):
        elo_rating = 200
    
    # Your existing mapping...
    if elo_rating <= 200:    skill = 0
    elif elo_rating <= 400:  skill = 0
    elif elo_rating <= 800:  skill = 2
    # ... (rest of your mapping)
    else:                    skill = 20

    try:
        # We open the "brain" ONLY ONCE here
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            engine.configure({"Skill Level": skill})
            
            # 1. GET THE MOVE AND EVAL SIMULTANEOUSLY
            if elo_rating <= 200:
                # Fresh Beginner: Depth 1
                limit = chess.engine.Limit(depth=1)
            else:
                # Higher levels: Time and Node limits
                node_limit = 1000 if skill == 0 else None
                limit = chess.engine.Limit(time=0.1, nodes=node_limit)
            
            # This is the pro way: play the move and get info back
            result = engine.play(board, limit)
            board.push(result.move)

            # 2. QUICK EVAL: Instead of calling get_evaluation() again,
            # we do one tiny, super-fast analysis of the new position.
            # This takes almost zero time since the engine is already open.
            info = engine.analyse(board, chess.engine.Limit(time=0.01))
            score = info["score"].white()
            
            # Format the score (Handle Mates vs Centipawns)
            if score.is_mate():
                eval_val = f"M{score.mate()}"
            else:
                eval_val = score.score() / 100.0 if score.score() is not None else 0.0
            
            return jsonify({
                "move": result.move.uci(),
                "fen": board.fen(),
                "evaluation": eval_val  # No second engine instance needed!
            })

    except Exception as e:
        print(f"PYTHON ERROR: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':

    app.run(debug=True)