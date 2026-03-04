from flask import Flask, render_template, request, jsonify

import chess

import chess.engine

import random

import os

from google import genai

from google.genai import types



app = Flask(__name__)




# --- GEMINI AI SETUP (NEW SDK) ---
# --- Initialize a Global Board State
# Replace with your newly generated key later!
GOOGLE_API_KEY = "AIzaSyC0VtmX-hSf2lOAYmC8e3-Wy0yQNeA7J_Q"
client = genai.Client(api_key=GOOGLE_API_KEY)

system_instruction = (
    "You are a Grandmaster chess coach talking to your student. "
    "Explain the reasoning behind the last move played. "
    "Use the provided Stockfish evaluation difference to determine if it was a good move, an inaccuracy, or a blunder. "
    "Keep your explanation conversational, encouraging, and UNDER 3 sentences. "
    "Do not output raw FEN strings to the user, just talk about the strategy in plain English."
)

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
    
    # --- CRASH FIX: Check if the game is already over! ---
    if board.is_game_over():
        return jsonify({"game_over": True, "fen": board.fen()})

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
        # --- THE TRUE 200 ELO FIX: The Blunder Injection ---
        # 40% of the time, the 200 Elo bot will just pick a completely random legal move.
        if elo_rating <= 200 and random.random() < 0.40:
            random_move = random.choice(list(board.legal_moves))
            board.push(random_move)
            
            # We still quickly open the engine just to get the evaluation number
            with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
                info = engine.analyse(board, chess.engine.Limit(time=0.01))
                score = info["score"].white()
                if score.is_mate(): eval_val = f"M{score.mate()}"
                else: eval_val = score.score() / 100.0 if score.score() is not None else 0.0
                
            return jsonify({
                "move": random_move.uci(),
                "fen": board.fen(),
                "evaluation": eval_val
            })

        # --- NORMAL ENGINE LOGIC (For 400+ Elo, or the other 60% of 200 Elo moves) ---
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            engine.configure({
                "Skill Level": skill,
                "Threads": 1,
                "Hash": 16
            })

            if elo_rating <= 200:
                limit = chess.engine.Limit(time=0.01, depth=1)
            else:
                node_limit = 1000 if skill == 0 else None
                limit = chess.engine.Limit(time=0.01, nodes=node_limit)
            
            result = engine.play(board, limit)
            
            # Safety net just in case
            if result.move is None:
                return jsonify({"game_over": True, "fen": board.fen()})
                
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
    

@app.route('/explain_move', methods=['POST'])
def explain_move():
    global board
    
    # If no moves have been made yet, we can't explain anything!
    if len(board.move_stack) == 0:
        return jsonify({"status": "error", "message": "Make a move first so I can analyze it!"})
    
    try:
        # 1. Get CURRENT state
        current_fen = board.fen()
        current_eval = get_evaluation(current_fen)
        
        # 2. Get PREVIOUS state
        # Temporarily undo the move to see what the board looked like before
        last_move = board.pop()
        san_move = board.san(last_move) # e.g., gets "Nf3" instead of "g1f3"
        
        prev_fen = board.fen()
        prev_eval = get_evaluation(prev_fen)
        
        # Put the move back so we don't ruin the game!
        board.push(last_move)
        
        # 3. Construct the prompt with the mathematical truth from Stockfish
        prompt = f"""
        Previous Position (FEN): {prev_fen}
        Previous Evaluation: {prev_eval} (Positive = White winning, Negative = Black winning)
        Move Played: {san_move}
        New Position (FEN): {current_fen}
        New Evaluation: {current_eval}
        
        Please explain this move to me.
        """
        
        # 4. Call Google Gemini (using the new SDK)
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
                max_output_tokens=5000,
            )
        )
        
        # 5. Send it back to the frontend chatbox
        return jsonify({"status": "success", "explanation": response.text})

    except Exception as e:
        print(f"!!! GEMINI COACH ERROR: {str(e)}")
        # Safety catch: If we popped the move but an error happened, put it back!
        if len(board.move_stack) < len(board.move_stack) + 1 and 'last_move' in locals():
            try: board.push(last_move) 
            except: pass
        return jsonify({"status": "error", "message": "My brain disconnected from Google. Check the console!"})

if __name__ == '__main__':

    app.run(debug=True)