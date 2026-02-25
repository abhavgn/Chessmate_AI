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
    data = request.json
    move_text = data.get("move")

    print(f"Attempting move: {move_text} | Current Turn: {'White' if board.turn else 'Black'}")

    try:
        move = chess.Move.from_uci(move_text)

        if move in board.legal_moves:
            board.push(move)
            current_eval = get_evaluation(board.fen())
            
            return jsonify({
                "status": "success",
                "fen": board.fen(),
                "check": board.is_check(),
                "turn": "white" if board.turn == chess.WHITE else "black",
                "evaluation": current_eval
            })
        else:
            # --- SILENT BOT DEBUGGER ADDED HERE ---
            print(f"!!! INVALID MOVE: {move_text} is not legal in this position.")
            print(f"!!! Current Python Board FEN: {board.fen()}")
            return jsonify({"status": "invalid", "message": "That move is against the rules!"}), 400
            
    except Exception as e:
        print(f"!!! ERROR DURING MOVE: {str(e)}")
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
        raw_level = data.get("level")
        elo_rating = int(raw_level) if raw_level is not None else 200
    except (TypeError, ValueError):
        elo_rating = 200
    
    if elo_rating <= 200:    skill = 0
    elif elo_rating <= 400:  skill = 0
    elif elo_rating <= 800:  skill = 2
    elif elo_rating <= 1200: skill = 5
    elif elo_rating <= 1600: skill = 10
    elif elo_rating <= 2000: skill = 14
    elif elo_rating <= 2400: skill = 17
    else:                    skill = 20

    try:
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            engine.configure({"Skill Level": skill})
            
        # FORCE these parameters to degrade the engine's intelligence
            engine.configure({
                "Skill Level": skill,
                "UCI_LimitStrength": "true",
                "UCI_Elo": 200 if elo_rating <= 200 else elo_rating,
                "Threads": 1,           # Slow it down
                "Hash": 16              # Shrink its memory so it can't "remember" patterns
            })

            if elo_rating <= 200:
                # ADDED STRICT TIME LIMIT HERE
                limit = chess.engine.Limit(time=0.01, depth=1)
            else:
                node_limit = 1000 if skill == 0 else None
                # ADDED STRICT TIME LIMIT HERE
                limit = chess.engine.Limit(time=0.01, nodes=node_limit)
            
            result = engine.play(board, limit)
            board.push(result.move)

            info = engine.analyse(board, chess.engine.Limit(time=0.01))
            score = info["score"].white()
            
            if score.is_mate():
                eval_val = f"M{score.mate()}"
            else:
                eval_val = score.score() / 100.0 if score.score() is not None else 0.0
            
            return jsonify({
                "move": result.move.uci(),
                "fen": board.fen(),
                "evaluation": eval_val
            })

    except Exception as e:
        print(f"PYTHON ERROR: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':

    app.run(debug=True)