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

    STRICT RULES:
    1. **Function First:** Explain what a move DOES for the board (e.g., controls a square, opens a diagonal, hangs a piece).
    2. **Grounding Rule:** ONLY discuss pieces and squares provided in the DATA. Do not invent theoretical threats, "vulnerable knights," or phantom pieces. 
    3. **The Assassin Rule:** If a move is a Mistake, Blunder, or Missing Checkmate, you MUST identify exactly which opponent piece will execute the 'Engine's Best Next Move'.
    4. **Tone & Length:** Blunt, insightful, and "Best by test." Maximum 3 to 4 sentences. Zero fluff.
    
    CATEGORICAL RESPONSES:
    - **Opening/Book Move:** Focus on development, space, and unlocking pieces.
    - **Good/Positional:** Explain the "Job" the piece is doing (e.g., reinforcing control, developing while flexible).
    - **Inaccuracy:** Note the loss of "tempo" or slow play. Don't call it a blunder, just point out it gives the opponent an easy path.
    - **Mistake:** Mention the passive play or slight tactical pressure they ignored.
    - **Blunder:** Identify exactly what is hanging and which opponent piece will capture it based on the 'Engine's Best Next Move'.
    - **Missing Checkmate:** Be harsh. Explain they ignored a back-rank mate or fatal threat, and state how the 'Engine's Best Next Move' ends the game.
    - **Missed Win:** You MUST state the 'Missed Best Move' from the DATA. Explain what that specific move would have achieved (e.g., immediate checkmate or winning major material) instead of the move they actually played.
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
    elif elo_rating <= 800:  skill = 1
    elif elo_rating <= 1200: skill = 4
    elif elo_rating <= 1600: skill = 5
    elif elo_rating <= 2000: skill = 12
    elif elo_rating <= 2400: skill = 15
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
    
def get_pins_and_attacks(board, square):
    # This checks if a piece on a specific square is pinned to the king
    is_pinned = board.is_pinned(board.turn, square)
    
    # This finds all pieces attacking that square
    attackers = board.attackers(not board.turn, square)
    attacker_names = [chess.piece_name(board.piece_at(s).piece_type) for s in attackers if board.piece_at(s)]
    
    return is_pinned, attacker_names

def get_tactical_facts(board):
    facts = []
    # Identify Absolute Pins (Pieces pinned to the King)
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece:
            pin_info = board.pin(piece.color, sq)
            # If the piece is pinned, pin_info will contain more than just its own square
            if board.is_pinned(piece.color, sq):
                # Find the pinner (the enemy piece attacking the line)
                attackers = board.attackers(not piece.color, sq)
                for a_sq in attackers:
                    # Check if this attacker is the one actually pinning it
                    if a_sq in pin_info:
                        pinner = board.piece_at(a_sq)
                        facts.append(f"The {chess.piece_name(piece.piece_type)} on {chess.square_name(sq)} is pinned to the King by the {chess.piece_name(pinner.piece_type)} on {chess.square_name(a_sq)}.")
    
    return "\n".join(facts) if facts else "No absolute pins currently on the board."

def get_material_score(board):
    # Standard piece values
    values = {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9
    }
    
    white_score = 0
    black_score = 0
    
    for piece_type in values:
        white_score += len(board.pieces(piece_type, chess.WHITE)) * values[piece_type]
        black_score += len(board.pieces(piece_type, chess.BLACK)) * values[piece_type]
    
    diff = white_score - black_score
    
    if diff == 0:
        return "Material is even."
    elif diff > 0:
        return f"White is +{diff} in material."
    else:
        return f"Black is +{abs(diff)} in material."

def get_tactical_context(board, target_sq):
    facts = []
    
    # 1. Check for Absolute Pins
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == board.turn:
            if board.is_pinned(board.turn, sq):
                pinner_sq = board.attackers(not board.turn, sq) # Find who is pinning it
                for ps in pinner_sq:
                    pinner = board.piece_at(ps)
                    facts.append(f"The {chess.piece_name(piece.piece_type)} on {chess.square_name(sq)} is pinned to the King by the {chess.piece_name(pinner.piece_type)} on {chess.square_name(ps)}.")

    # 2. Identify Attackers on the target square (where the best move goes)
    attackers = board.attackers(not board.turn, target_sq)
    for a_sq in attackers:
        a_piece = board.piece_at(a_sq)
        facts.append(f"The {chess.piece_name(a_piece.piece_type)} on {chess.square_name(a_sq)} is attacking {chess.square_name(target_sq)}.")

    return "\n".join(facts) if facts else "No immediate pins or direct trades detected."

@app.route('/game_summary', methods=['POST'])
def game_summary():
    data = request.json
    pgn = data.get('pgn')
    bot_elo = data.get('bot_elo', 400)

    if not pgn:
        return jsonify({"status": "error", "message": "No game history found."})

    try:
        # The prompt is designed to be grounded and critical
        response = client.chat.completions.create(
            model="gpt-4o", # Or your specific model version
            messages=[
                {"role": "system", "content": f"""You are 'James', a high-level Chess Coach. 
                You are reviewing a game played by a student against a {bot_elo} ELO bot.
                
                CRITICAL INSTRUCTIONS:
                1. Analyze the provided PGN move-by-move.
                2. Do NOT mention moves that did not happen. 
                3. Identify the Opening used.
                4. Find the 'Turning Point' (the move where the evaluation swung).
                5. Be encouraging but honest about blunders.
                6. Format the summary into three distinct sections: 1. Opening Analysis, 2. The Turning Point, and 3. Coach's Tip for Improvement.
                7. Use markdown for emphasis (e.g., **Nf3**)."""},
                {"role": "user", "content": f"Here is the game PGN:\n{pgn}\n\nPlease summarize my performance."}
            ],
            temperature=0.7
        )

        summary_text = response.choices[0].message.content
        return jsonify({"status": "success", "summary": summary_text})

    except Exception as e:
        print(f"Error in summary: {e}")
        return jsonify({"status": "error", "message": str(e)})

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
        if mode == 'play' and temp_board.turn == chess.WHITE and len(temp_board.move_stack) >= 2:
            temp_board.pop() # Remove AI move
            
        user_move = temp_board.pop()
        
        # --- THIS IS YOUR 'BOARD_BEFORE_MOVE' ---
        # temp_board is now exactly the state before the user moved.
        
        # 2. Get data BEFORE the move
        fen_before = temp_board.fen()
        prev_eval = get_evaluation(fen_before)
        
        # NEW: Find the Missed Best Move (what the engine wanted you to do)
        missed_best_move = "None"
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info_before = engine.analyse(temp_board, chess.engine.Limit(time=0.1))
            if "pv" in info_before and len(info_before["pv"]) > 0:
                missed_best_move = temp_board.san(info_before["pv"][0])

        moving_piece = temp_board.piece_at(user_move.from_square)
        moving_piece_name = chess.piece_name(moving_piece.piece_type).capitalize() if moving_piece else "Piece"
        san_move = temp_board.san(user_move)

        # 3. Apply the move and get data AFTER
        temp_board.push(user_move)
        fen_after = temp_board.fen()
        current_eval = get_evaluation(fen_after)

        # 4. Engine Refutation (Opponent's best response)
        punishment_move = "None"
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info_after = engine.analyse(temp_board, chess.engine.Limit(time=0.1))
            if "pv" in info_after and len(info_after["pv"]) > 0:
                punishment_move = temp_board.san(info_after["pv"][0])

        # --- IDENTIFY THE ASSASSIN ---
        punishing_piece = "opponent"
        if punishment_move != "None":
            p_char = punishment_move[0]
            piece_map = {'Q': 'Queen', 'R': 'Rook', 'B': 'Bishop', 'N': 'Knight', 'K': 'King'}
            punishing_piece = piece_map.get(p_char, "Pawn")

        # 5. MATH & CATEGORY DETECTION
        category = "Good/Positional Move" 
        eval_delta = 0.0
        
        try:
            def parse_eval(e):
                if isinstance(e, str) and "M" in e:
                    return 20.0 if not "-" in e else -20.0
                return float(e)
            
            p_val = parse_eval(prev_eval)
            c_val = parse_eval(current_eval)
            eval_delta = c_val - p_val
            turn_count = len(temp_board.move_stack)

            if isinstance(current_eval, str) and "M-" in current_eval:
                category = "Missing Checkmate"
            elif p_val > 2.5 and eval_delta < -2.0: # Significant drop from a winning position
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

        # 6. Final Prompt Construction
        # Use punishment_move for the logic now that we've cleaned the code
        ai_facing_punishment = punishment_move if category not in ["Opening/Book Move", "Good/Positional Move"] else "N/A"

        prompt = f"""
        DATA:
        - Piece Moved: {moving_piece_name}
        - Move Played: {san_move}
        - Move Category: {category}
        - Evaluation Change: {round(eval_delta, 2)} points
        - Engine's Best Next Move (Opponent Response): {ai_facing_punishment}
        - Punishing Piece: {punishing_piece}
        - Missed Best Move: {missed_best_move}
        - Current Board FEN: {fen_after}

        TASK:
        Based on the 'Move Category' of [{category}], explain the move {san_move}. 
        - If [{category}] is 'Inaccuracy', 'Mistake', 'Blunder', or 'Missing Checkmate', use the 'Engine's Best Next Move' to explain exactly how the opponent's {punishing_piece} will punish the user. 
        - If [{category}] is 'Missed Win', strictly focus on how they failed to play {missed_best_move} and what {missed_best_move} would have accomplished.
        - If [{category}] is 'Opening' or 'Good', STRICTLY IGNORE the opponent's next move and the missed move. Only explain why {san_move} works well.
        """
        
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        return jsonify({"status": "success", "explanation": response.choices[0].message.content})

    except Exception as e:
        print(f"!!! OPENAI COACH ERROR: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to analyze move."})
    

@app.route('/best_move', methods=['POST'])
def best_move():
    data = request.json
    current_fen = data.get("fen")

    # Calculate the actual move number (e.g., Move 1, Move 12)
    move_number = (len(board.move_stack) // 2) + 1
    
    temp_board = chess.Board(current_fen) if current_fen else chess.Board()

    if temp_board.is_game_over():
        return jsonify({"status": "error", "message": "The game is already over!"})
    

    material_status = get_material_score(temp_board)
    tactical_facts = get_tactical_facts(temp_board)

    try:
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            # We use depth=15 or a slightly longer time to get a solid tactical line
            info = engine.analyse(temp_board, chess.engine.Limit(time=1.5))
            
            # 1. Get the primary move
            best_move_obj = info["pv"][0]
            san_move = temp_board.san(best_move_obj)
            
            # 2. Extract the "Expected Continuation" (The next 3-4 moves)
            # This is the secret sauce that stops the AI from hallucinating
            pv_san = []
            test_board = temp_board.copy()
            
            for m in info["pv"][:4]: 
                turn_label = "White" if test_board.turn == chess.WHITE else "Black"
                pv_san.append(f"{turn_label} plays {test_board.san(m)}")
                test_board.push(m)
                
            expected_line_list = "\n".join([f"- {m}" for m in pv_san])

            # NEW: Get the game history to identify openings
            game_history = []
            hist_board = chess.Board()
            # Use the global board to get the moves played so far
            for move in board.move_stack:
                game_history.append(hist_board.san(move))
                hist_board.push(move)
            history_str = " ".join(game_history)
            
            moving_piece = temp_board.piece_at(best_move_obj.from_square)
            moving_piece_name = chess.piece_name(moving_piece.piece_type).capitalize() if moving_piece else "Piece"

        # 3. The newly structured prompt with the "Best Reply" rule
        # In your route, call the function first:
        tactical_facts = get_tactical_facts(temp_board)

        prompt = f"""
            DATA:
            - Move Number: {move_number}
            - Recommended Move: {san_move}
            - Piece Moving: {moving_piece_name}
            - Material Status: {material_status}
            - Tactical Facts (Ground Truth): {tactical_facts}
            - Engine's Expected Continuation: {expected_line_list}
            - Current Board FEN: {temp_board.fen()}

            TASK:
            Explain exactly WHY {san_move} is the best move.
            
            STRICT RULES:
            1. **The "Copy-Paste" Rule:** When mentioning the opponent's best response, YOU MUST copy the move EXACTLY as it appears in the 'Engine's Expected Continuation'. If the data says "Black plays Ke6", YOU MUST NOT say "Black plays Be6" or "Black blocks with the bishop." 
            2. **Coordinate Lockdown:** Do not mention any square (like e7 or d5) unless it is explicitly mentioned in the 'Tactical Facts' or 'Expected Continuation'. 
            3. **Piece Identity:** Double-check the piece type. If the data says 'K', it is a King. If 'B', it is a Bishop. Do not swap them.
            4. **The "Best Reply" Rule:** Use phrases like "The best response is [EXACT MOVE FROM DATA], but you still maintain the initiative."
            5. Tone: Practical, blunt, and instructive. Max 3 sentences.
            """
        
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        # Inside your /best_move route in app.py
        return jsonify({
            "status": "success", 
            "move": san_move, 
            "from_sq": best_move_obj.from_square, # Integer 0-63
            "to_sq": best_move_obj.to_square,     # Integer 0-63
            "explanation": response.choices[0].message.content
        })

    except Exception as e:
        print(f"!!! BEST MOVE ERROR: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to suggest a move."})
    

if __name__ == '__main__':
    app.run(debug=True)