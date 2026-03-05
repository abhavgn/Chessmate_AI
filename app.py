from flask import Flask, render_template, request, jsonify
import chess
import chess.engine
import random
import os
from dotenv import load_dotenv
from openai import OpenAI

# Load the environment variables securely from the .env file
load_dotenv()

app = Flask(__name__)

# --- OPENAI AI SETUP ---
# It will securely grab OPENAI_API_KEY from your .env file
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

system_instruction = (
    """
    You are a practical, insightful, and slightly blunt chess coach. 
    Your job is to analyze the user's last move based on development, central space, piece mobility, and tactical threats.

    RULES:
    1. **Function First:** Explain what a move DOES for the board (e.g., controls a square, opens a diagonal, hangs a piece).
    2. **Grounding Rule:** ONLY discuss pieces and squares provided in the DATA. Do not invent theoretical threats, "vulnerable knights," or phantom pieces. 
    3. **Tone & Length:** Blunt, insightful, and "Best by test." Maximum 3 to 4 sentences. Zero fluff.
    4. **Categorical Responses:** Tailor your response perfectly to the 'Move Category' provided in the DATA:
       - If 'Opening/Book Move': Focus on development, space, and unlocking pieces.
       - If 'Good/Positional': Explain the "Job" the piece is doing (e.g., reinforcing control, developing while flexible).
       - If 'Inaccuracy': Note the loss of "tempo" or slow play. Don't call it a blunder, just point out it gives the opponent an easy path.
       - If 'Mistake': Mention the missed opportunity, passive play, or slight tactical pressure they ignored.
       - If 'Blunder': Identify exactly what is hanging and which opponent piece will capture it based on the 'Engine Punishment'.
       - If 'Missing Checkmate': Be harsh. Explain they ignored a back-rank mate or fatal threat, and state the 'Engine Punishment' ends the game.
       - If 'Missed Win': Point out the massive opportunity they missed (e.g., a free piece or a mate) instead of what they played.
    """
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
        
        if score.is_mate():
            mate_val = score.mate()
            return f"M{mate_val}" if mate_val is not None else "M"
        
        val = score.score()
        return val / 100.0 if val is not None else 0.0

@app.route('/move', methods=['POST'])
def make_move():
    global board
    data = request.json
    move_text = data.get("move")

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
        if elo_rating <= 200 and random.random() < 0.40:
            random_move = random.choice(list(board.legal_moves))
            board.push(random_move)
            
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

        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            engine.configure({"Skill Level": skill, "Threads": 1, "Hash": 16})
            limit = chess.engine.Limit(time=0.01, depth=1) if elo_rating <= 200 else chess.engine.Limit(time=0.01, nodes=(1000 if skill == 0 else None))
            
            result = engine.play(board, limit)
            if result.move is None:
                return jsonify({"game_over": True, "fen": board.fen()})
                
            board.push(result.move)

            info = engine.analyse(board, chess.engine.Limit(time=0.01))
            score = info["score"].white()
            eval_val = f"M{score.mate()}" if score.is_mate() else (score.score() / 100.0 if score.score() is not None else 0.0)
            
            return jsonify({
                "move": result.move.uci(),
                "fen": board.fen(),
                "evaluation": eval_val
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/explain_move', methods=['POST'])
def explain_move():
    global board
    data = request.json or {}
    mode = data.get("mode", "analysis")
    
    if len(board.move_stack) == 0:
        return jsonify({"status": "error", "message": "Make a move first!"})
    
    temp_board = board.copy()

    try:
        # 1. Back up to the state BEFORE the user's last move
        moves_to_pop = 1
        if mode == 'play' and temp_board.turn == chess.WHITE and len(temp_board.move_stack) >= 2:
            temp_board.pop() 
            moves_to_pop = 1 
            
        user_move = temp_board.pop()
        
        # 2. Get evaluation and data BEFORE the move
        fen_before = temp_board.fen()
        prev_eval = get_evaluation(fen_before)
        
        moving_piece = temp_board.piece_at(user_move.from_square)
        moving_piece_name = chess.piece_name(moving_piece.piece_type).capitalize() if moving_piece else "Piece"
        
        san_move = temp_board.san(user_move)

        # 3. Apply the move and get evaluation AFTER
        temp_board.push(user_move)
        fen_after = temp_board.fen()
        current_eval = get_evaluation(fen_after)

        # 4. Engine Refutation (looking one move ahead)
        punishment_move = "None"
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info = engine.analyse(temp_board, chess.engine.Limit(time=0.1))
            if "pv" in info and len(info["pv"]) > 0:
                punishment_move = temp_board.san(info["pv"][0])

        # 5. MATH & CATEGORY DETECTION
        category = "Good/Positional Move" # Default
        eval_delta = 0.0
        
        try:
            # Safely parse evaluations (handling 'M4', 'M-2', etc.)
            def parse_eval(e):
                if isinstance(e, str) and "M" in e:
                    return 20.0 if not "-" in e else -20.0
                return float(e)
            
            p_val = parse_eval(prev_eval)
            c_val = parse_eval(current_eval)
            eval_delta = c_val - p_val
            turn_count = len(temp_board.move_stack)

            # Categorize the move based on engine data
            if isinstance(current_eval, str) and "M-" in current_eval:
                category = "Missing Checkmate"
            elif p_val > 3.0 and c_val < 1.0:
                category = "Missed Win"
            elif eval_delta <= -3.0:
                category = "Blunder"
            elif eval_delta <= -1.2:
                category = "Mistake"
            elif eval_delta <= -0.6:
                category = "Inaccuracy"
            elif turn_count <= 10 and eval_delta >= -0.4:
                category = "Opening/Book Move"
                
        except Exception as math_e:
            print(f"Eval Math Error: {math_e}")
            eval_delta = 0

        # 6. Formatting the Prompt
        # NEW FIX: Only give the AI the opponent's response if there is an actual punishment!
        if category in ["Opening/Book Move", "Good/Positional Move"]:
            ai_facing_punishment = "N/A - This was a good move, focus only on why the user's move is good."
        else:
            ai_facing_punishment = punishment_move

        formatted_system_instruction = system_instruction # Already defined globally

        prompt = f"""
        DATA:
        - Piece Moved: {moving_piece_name}
        - Move Played: {san_move}
        - Move Category: {category}
        - Evaluation Change: Dropped/Gained by {round(eval_delta, 2)} points
        - Engine's Best Next Move (Opponent Response): {ai_facing_punishment}
        - Current Board FEN: {fen_after}

        TASK:
        Based on the 'Move Category' of [{category}], explain the move {san_move}. 
        If it's an inaccuracy, mistake, or blunder, use the 'Engine's Best Next Move' to explain exactly what the opponent will do to punish the move. 
        If it's an Opening or Good move, STRICTLY IGNORE the opponent's next move and explain why the user's move works well.
        """
        
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": formatted_system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        return jsonify({"status": "success", "explanation": response.choices[0].message.content})

    except Exception as e:
        print(f"!!! OPENAI COACH ERROR: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to analyze move."})

if __name__ == '__main__':
    app.run(debug=True)