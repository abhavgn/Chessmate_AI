from flask import Flask, render_template, request, jsonify
import chess
import chess.engine
import random
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = Flask(__name__)

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
            return jsonify({"move": random_move.uci(), "fen": board.fen(), "evaluation": eval_val})

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
            return jsonify({"move": result.move.uci(), "fen": board.fen(), "evaluation": eval_val})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── HELPER FUNCTIONS ────────────────────────────────────────────────────────

def get_pins_and_attacks(board, square):
    is_pinned = board.is_pinned(board.turn, square)
    attackers = board.attackers(not board.turn, square)
    attacker_names = [chess.piece_name(board.piece_at(s).piece_type) for s in attackers if board.piece_at(s)]
    return is_pinned, attacker_names

def get_tactical_facts(board):
    facts = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece:
            pin_info = board.pin(piece.color, sq)
            if board.is_pinned(piece.color, sq):
                attackers = board.attackers(not piece.color, sq)
                for a_sq in attackers:
                    if a_sq in pin_info:
                        pinner = board.piece_at(a_sq)
                        facts.append(f"The {chess.piece_name(piece.piece_type)} on {chess.square_name(sq)} is pinned to the King by the {chess.piece_name(pinner.piece_type)} on {chess.square_name(a_sq)}.")
    return "\n".join(facts) if facts else "No absolute pins currently on the board."

def get_material_score(board):
    values = {
        chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
        chess.ROOK: 5, chess.QUEEN: 9
    }
    white_score = sum(len(board.pieces(pt, chess.WHITE)) * v for pt, v in values.items())
    black_score = sum(len(board.pieces(pt, chess.BLACK)) * v for pt, v in values.items())
    diff = white_score - black_score
    if diff == 0:   return "Material is even."
    elif diff > 0:  return f"White is +{diff} in material."
    else:           return f"Black is +{abs(diff)} in material."

def get_tactical_context(board, target_sq):
    facts = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == board.turn:
            if board.is_pinned(board.turn, sq):
                pinner_sq = board.attackers(not board.turn, sq)
                for ps in pinner_sq:
                    pinner = board.piece_at(ps)
                    facts.append(f"The {chess.piece_name(piece.piece_type)} on {chess.square_name(sq)} is pinned to the King by the {chess.piece_name(pinner.piece_type)} on {chess.square_name(ps)}.")
    attackers = board.attackers(not board.turn, target_sq)
    for a_sq in attackers:
        a_piece = board.piece_at(a_sq)
        facts.append(f"The {chess.piece_name(a_piece.piece_type)} on {chess.square_name(a_sq)} is attacking {chess.square_name(target_sq)}.")
    return "\n".join(facts) if facts else "No immediate pins or direct trades detected."

def get_game_phase(board):
    total_pieces = (len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK)) +
                    len(board.pieces(chess.ROOK, chess.WHITE))  + len(board.pieces(chess.ROOK, chess.BLACK)) +
                    len(board.pieces(chess.BISHOP, chess.WHITE))+ len(board.pieces(chess.BISHOP, chess.BLACK)) +
                    len(board.pieces(chess.KNIGHT, chess.WHITE))+ len(board.pieces(chess.KNIGHT, chess.BLACK)))
    move_count = len(board.move_stack)
    if move_count <= 10:      return "Opening"
    elif total_pieces <= 6:   return "Endgame"
    else:                     return "Middlegame"

def get_king_safety(board, color):
    king_sq = board.king(color)
    if king_sq is None:
        return "Unknown"
    enemy_color = not color
    attackers = len(board.attackers(enemy_color, king_sq))
    adjacent = chess.SquareSet(chess.BB_KING_ATTACKS[king_sq])
    adj_attacks = sum(1 for sq in adjacent if board.attackers(enemy_color, sq))
    if attackers > 0:
        return f"King is directly attacked by {attackers} piece(s). {adj_attacks} adjacent squares are also under fire — King is in DANGER."
    elif adj_attacks >= 3:
        return f"King zone is under heavy pressure ({adj_attacks} adjacent squares attacked)."
    elif adj_attacks >= 1:
        return f"King has mild exposure ({adj_attacks} adjacent squares attacked)."
    else:
        return "King appears safe."

def get_open_files(board):
    open_files, semi_open_white, semi_open_black = [], [], []
    for file_idx in range(8):
        file_name = chess.FILE_NAMES[file_idx]
        white_pawns = any(board.piece_at(chess.square(file_idx, r)) == chess.Piece(chess.PAWN, chess.WHITE) for r in range(8))
        black_pawns = any(board.piece_at(chess.square(file_idx, r)) == chess.Piece(chess.PAWN, chess.BLACK) for r in range(8))
        if not white_pawns and not black_pawns:  open_files.append(file_name)
        elif not white_pawns:                    semi_open_white.append(file_name)
        elif not black_pawns:                    semi_open_black.append(file_name)
    result = []
    if open_files:        result.append(f"Open files: {', '.join(open_files)}-file(s)")
    if semi_open_white:   result.append(f"Semi-open for White: {', '.join(semi_open_white)}-file(s)")
    if semi_open_black:   result.append(f"Semi-open for Black: {', '.join(semi_open_black)}-file(s)")
    return "; ".join(result) if result else "No open files."

def get_piece_activity(board):
    white_mobility = black_mobility = 0
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.piece_type not in [chess.PAWN, chess.KING]:
            attacks = len(board.attacks(sq))
            if piece.color == chess.WHITE: white_mobility += attacks
            else:                          black_mobility += attacks
    return f"White piece activity: {white_mobility} squares controlled. Black piece activity: {black_mobility} squares controlled."


# ─── ADVANCED TACTICAL DETECTORS ─────────────────────────────────────────────

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 99
}

def piece_val(board, sq):
    p = board.piece_at(sq)
    return PIECE_VALUES.get(p.piece_type, 0) if p else 0

def pname(board, sq):
    p = board.piece_at(sq)
    return chess.piece_name(p.piece_type).capitalize() if p else "piece"

def sqname(sq):
    return chess.square_name(sq)

def get_recapture_info(board, move):
    to_sq = move.to_square
    moving_piece = board.piece_at(move.from_square)
    if not moving_piece:
        return None
    board.push(move)
    opponent = board.turn
    recapturers = list(board.attackers(opponent, to_sq))
    board.pop()
    if not recapturers:
        return None
    best_recapturer_sq = min(recapturers, key=lambda s: PIECE_VALUES.get(
        board.piece_at(s).piece_type if board.piece_at(s) else chess.PAWN, 99))
    recapturer = board.piece_at(best_recapturer_sq)
    if not recapturer:
        return None
    moved_value   = PIECE_VALUES.get(moving_piece.piece_type, 0)
    capture_value = piece_val(board, to_sq)
    recap_value   = PIECE_VALUES.get(recapturer.piece_type, 0)
    return {
        "can_recapture": True,
        "recapturer_piece": chess.piece_name(recapturer.piece_type).capitalize(),
        "recapturer_sq": sqname(best_recapturer_sq),
        "to_sq": sqname(to_sq),
        "moving_piece": chess.piece_name(moving_piece.piece_type).capitalize(),
        "moving_piece_value": moved_value,
        "recapturer_value": recap_value,
        "capture_value": capture_value,
        "material_lost": moved_value - capture_value,
    }

def detect_forks(board, move):
    board.push(move)
    to_sq = move.to_square
    moved_piece = board.piece_at(to_sq)
    if not moved_piece:
        board.pop()
        return None
    attacked_opponents = []
    for sq in board.attacks(to_sq):
        target = board.piece_at(sq)
        if target and target.color == board.turn:
            if target.piece_type != chess.PAWN or PIECE_VALUES.get(moved_piece.piece_type, 0) < PIECE_VALUES.get(target.piece_type, 0):
                attacked_opponents.append(f"{chess.piece_name(target.piece_type).capitalize()} on {sqname(sq)}")
    board.pop()
    if len(attacked_opponents) >= 2:
        return {
            "fork": True,
            "forking_piece": chess.piece_name(board.piece_at(move.from_square).piece_type).capitalize() if board.piece_at(move.from_square) else "Piece",
            "targets": attacked_opponents
        }
    return None

def get_hanging_pieces(board, color):
    hanging = []
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != color or piece.piece_type == chess.KING:
            continue
        attackers = list(board.attackers(not color, sq))
        defenders = list(board.attackers(color, sq))
        if attackers:
            min_attacker_val = min(PIECE_VALUES.get(board.piece_at(a).piece_type, 9) for a in attackers if board.piece_at(a))
            piece_value = PIECE_VALUES.get(piece.piece_type, 0)
            if not defenders or min_attacker_val < piece_value:
                attacker_sq = min(attackers, key=lambda a: PIECE_VALUES.get(board.piece_at(a).piece_type, 9) if board.piece_at(a) else 9)
                attacker_piece = board.piece_at(attacker_sq)
                hanging.append(
                    f"{chess.piece_name(piece.piece_type).capitalize()} on {sqname(sq)} "
                    f"(attacked by {chess.piece_name(attacker_piece.piece_type).capitalize()} on {sqname(attacker_sq)}, "
                    f"{'undefended' if not defenders else 'underdefended'})"
                )
    return hanging

def detect_discovered_attack(board, move):
    from_sq = move.from_square
    player_color = board.turn
    discovered = []
    piece = board.piece_at(from_sq)
    board.remove_piece_at(from_sq)
    for sq in chess.SQUARES:
        behind = board.piece_at(sq)
        if not behind or behind.color != player_color:
            continue
        if behind.piece_type not in [chess.BISHOP, chess.ROOK, chess.QUEEN]:
            continue
        for attack_sq in board.attacks(sq):
            target = board.piece_at(attack_sq)
            if target and target.color != player_color and target.piece_type != chess.PAWN:
                discovered.append(
                    f"{chess.piece_name(behind.piece_type).capitalize()} on {sqname(sq)} "
                    f"reveals attack on {chess.piece_name(target.piece_type).capitalize()} on {sqname(attack_sq)}"
                )
    board.set_piece_at(from_sq, piece)
    return discovered

def detect_skewers(board, move):
    board.push(move)
    to_sq = move.to_square
    moved = board.piece_at(to_sq)
    opponent = board.turn
    skewers = []
    if not moved or moved.piece_type not in [chess.BISHOP, chess.ROOK, chess.QUEEN]:
        board.pop()
        return skewers
    for attack_sq in board.attacks(to_sq):
        front = board.piece_at(attack_sq)
        if not front or front.color != opponent:
            continue
        front_val = PIECE_VALUES.get(front.piece_type, 0)
        direction = (chess.square_file(attack_sq) - chess.square_file(to_sq),
                     chess.square_rank(attack_sq) - chess.square_rank(to_sq))
        next_file = chess.square_file(attack_sq) + (1 if direction[0] > 0 else -1 if direction[0] < 0 else 0)
        next_rank = chess.square_rank(attack_sq) + (1 if direction[1] > 0 else -1 if direction[1] < 0 else 0)
        if 0 <= next_file <= 7 and 0 <= next_rank <= 7:
            behind_sq = chess.square(next_file, next_rank)
            behind = board.piece_at(behind_sq)
            if behind and behind.color == opponent:
                behind_val = PIECE_VALUES.get(behind.piece_type, 0)
                if front_val > behind_val:
                    skewers.append(
                        f"Skewer: {chess.piece_name(moved.piece_type).capitalize()} on {sqname(to_sq)} "
                        f"attacks {chess.piece_name(front.piece_type).capitalize()} on {sqname(attack_sq)}, "
                        f"with {chess.piece_name(behind.piece_type).capitalize()} on {sqname(behind_sq)} behind it"
                    )
    board.pop()
    return skewers

def detect_back_rank_weakness(board, color):
    back_rank = 0 if color == chess.WHITE else 7
    king_sq = board.king(color)
    if not king_sq or chess.square_rank(king_sq) != back_rank:
        return None
    pawns_blocking = 0
    for file in range(max(0, chess.square_file(king_sq)-1), min(8, chess.square_file(king_sq)+2)):
        sq = chess.square(file, back_rank)
        p = board.piece_at(sq)
        if p and p.piece_type == chess.PAWN and p.color == color:
            pawns_blocking += 1
    if pawns_blocking >= 2:
        opponent = not color
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.color == opponent and p.piece_type in [chess.ROOK, chess.QUEEN]:
                if chess.square_rank(sq) != back_rank:
                    return f"Back rank weakness: King on {sqname(king_sq)} is blocked by own pawns — vulnerable to back rank mate from {chess.piece_name(p.piece_type).capitalize()} on {sqname(sq)}"
    return None

def get_pawn_structure(board):
    facts = []
    for color in [chess.WHITE, chess.BLACK]:
        color_name = "White" if color == chess.WHITE else "Black"
        pawns = list(board.pieces(chess.PAWN, color))
        files = [chess.square_file(p) for p in pawns]
        for f in set(files):
            if files.count(f) > 1:
                facts.append(f"{color_name} has doubled pawns on the {chess.FILE_NAMES[f]}-file")
        for p in pawns:
            f = chess.square_file(p)
            neighbors = [chess.square_file(x) for x in pawns if x != p]
            if (f-1) not in neighbors and (f+1) not in neighbors:
                facts.append(f"{color_name} has an isolated pawn on {sqname(p)}")
        opponent = not color
        opp_pawns = list(board.pieces(chess.PAWN, opponent))
        for p in pawns:
            f = chess.square_file(p)
            r = chess.square_rank(p)
            is_passed = True
            for op in opp_pawns:
                of = chess.square_file(op)
                or_ = chess.square_rank(op)
                if abs(of - f) <= 1:
                    if (color == chess.WHITE and or_ > r) or (color == chess.BLACK and or_ < r):
                        is_passed = False
                        break
            if is_passed:
                facts.append(f"{color_name} has a passed pawn on {sqname(p)}")
    return "; ".join(facts) if facts else "No notable pawn structure issues."

def full_move_analysis(board, move):
    result = {
        "is_legal": move in board.legal_moves,
        "is_capture": board.is_capture(move),
        "gives_check": board.gives_check(move),
        "is_castling": board.is_castling(move),
        "is_en_passant": board.is_en_passant(move),
        "recapture": None, "fork": None,
        "discovered_attacks": [], "skewers": [],
        "hanging_before": [], "hanging_after": [],
        "back_rank_before": None, "back_rank_after": None,
        "pawn_structure": "",
    }
    if not result["is_legal"]:
        return result
    moving_piece = board.piece_at(move.from_square)
    captured_piece = board.piece_at(move.to_square)
    result["captured_piece"]  = chess.piece_name(captured_piece.piece_type).capitalize() if captured_piece else None
    result["captured_value"]  = PIECE_VALUES.get(captured_piece.piece_type, 0) if captured_piece else 0
    result["moving_piece"]    = chess.piece_name(moving_piece.piece_type).capitalize() if moving_piece else None
    result["moving_value"]    = PIECE_VALUES.get(moving_piece.piece_type, 0) if moving_piece else 0
    result["recapture"]       = get_recapture_info(board, move)
    result["fork"]            = detect_forks(board, move)
    result["discovered_attacks"] = detect_discovered_attack(board, move)
    result["skewers"]         = detect_skewers(board, move)
    player = board.turn
    result["hanging_before"]  = get_hanging_pieces(board, player)
    board.push(move)
    result["hanging_after"]   = get_hanging_pieces(board, not player)
    result["back_rank_after"] = detect_back_rank_weakness(board, not player)
    result["pawn_structure"]  = get_pawn_structure(board)
    board.pop()
    result["back_rank_before"] = detect_back_rank_weakness(board, not player)
    return result

def format_move_analysis_for_prompt(analysis, move_san):
    lines = []
    lines.append(f"MOVE: {move_san}")
    lines.append(f"Is Capture: {analysis['is_capture']} (captured: {analysis.get('captured_piece','nothing')}, value: {analysis.get('captured_value',0)} pts)")
    lines.append(f"Gives Check: {analysis['gives_check']}")
    lines.append(f"Is Castling: {analysis['is_castling']}")
    lines.append(f"Is En Passant: {analysis['is_en_passant']}")

    # FIX 1: Recapture warning now clearly names what was captured AND what recaptures
    if analysis["recapture"]:
        r = analysis["recapture"]
        captured_val = analysis.get('captured_value', 0)
        captured_name = analysis.get('captured_piece', 'piece') or 'piece'
        net_loss = r['moving_piece_value'] - captured_val
        lines.append(
            f"RECAPTURE WARNING: Your {r['moving_piece']} captures the {captured_name} on {r['to_sq']} "
            f"(worth {captured_val} pts), BUT opponent's {r['recapturer_piece']} on {r['recapturer_sq']} "
            f"immediately takes back your {r['moving_piece']} on {r['to_sq']} (worth {r['moving_piece_value']} pts). "
            f"You gain {captured_val} pts but lose {r['moving_piece_value']} pts — net loss of {net_loss} pts. "
            f"This is NOT a free capture."
        )
    else:
        lines.append("Recapture: No opponent piece can recapture on the destination square.")

    if analysis["fork"]:
        f = analysis["fork"]
        lines.append(f"FORK CREATED: {f['forking_piece']} forks {', '.join(f['targets'])}")
    if analysis["discovered_attacks"]:
        lines.append("DISCOVERED ATTACKS: " + "; ".join(analysis["discovered_attacks"]))
    if analysis["skewers"]:
        lines.append("SKEWERS: " + "; ".join(analysis["skewers"]))
    if analysis["hanging_before"]:
        lines.append("YOUR PIECES HANGING BEFORE MOVE: " + "; ".join(analysis["hanging_before"]))
    if analysis["hanging_after"]:
        lines.append("OPPONENT PIECES HANGING AFTER MOVE: " + "; ".join(analysis["hanging_after"]))
    if analysis["back_rank_before"]:
        lines.append(f"BACK RANK THREAT (before move): {analysis['back_rank_before']}")
    if analysis["back_rank_after"]:
        lines.append(f"BACK RANK THREAT (after move): {analysis['back_rank_after']}")
    lines.append(f"Pawn Structure: {analysis['pawn_structure']}")
    return "\n".join(lines)


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route('/game_summary', methods=['POST'])
def game_summary():
    data = request.json
    pgn = data.get('pgn')
    bot_elo = data.get('bot_elo', 400)
    player_color = data.get('player_color', 'white')
    player_side  = "White" if player_color == 'white' else "Black"
    engine_side  = "Black" if player_color == 'white' else "White"

    if not pgn:
        return jsonify({"status": "error", "message": "No game history found."})

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": f"""You are 'James', a high-level Chess Coach. 
                You are reviewing a game where the STUDENT played as {player_side} and the {bot_elo} ELO bot played as {engine_side}.
                
                CRITICAL INSTRUCTIONS:
                1. Analyze the provided PGN move-by-move.
                2. Do NOT mention moves that did not happen. 
                3. Identify the Opening used.
                4. Find the 'Turning Point' (the move where the evaluation swung).
                5. Be encouraging but honest about blunders.
                6. Always refer to the student's moves as {player_side}'s moves. Never confuse which side the student was on.
                7. Format the summary into three distinct sections: 1. Opening Analysis, 2. The Turning Point, and 3. Coach's Tip for Improvement.
                8. Use markdown for emphasis (e.g., **Nf3**)."""},
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
    player_color = data.get("player_color", "white")
    frontend_history = data.get("history", [])

    if frontend_history:
        temp_board = chess.Board()
        for san in frontend_history:
            try:
                move = temp_board.parse_san(san)
                temp_board.push(move)
            except Exception:
                pass
        board = temp_board.copy()
    else:
        temp_board = board.copy()

    if len(temp_board.move_stack) == 0:
        return jsonify({"status": "error", "message": "Make a move first!"})

    try:
        if mode == 'play' and len(temp_board.move_stack) >= 2:
            player_chess_color = chess.BLACK if player_color == 'black' else chess.WHITE
            if temp_board.turn == player_chess_color:
                temp_board.pop()

        user_move = temp_board.pop()
        fen_before = temp_board.fen()
        prev_eval = get_evaluation(fen_before)

        missed_best_move = "None"
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info_before = engine.analyse(temp_board, chess.engine.Limit(time=0.1))
            if "pv" in info_before and len(info_before["pv"]) > 0:
                missed_best_move = temp_board.san(info_before["pv"][0])

        moving_piece = temp_board.piece_at(user_move.from_square)
        moving_piece_name = chess.piece_name(moving_piece.piece_type).capitalize() if moving_piece else "Piece"
        san_move = temp_board.san(user_move)

        temp_board.push(user_move)
        fen_after = temp_board.fen()
        current_eval = get_evaluation(fen_after)

        punishment_move = "None"
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info_after = engine.analyse(temp_board, chess.engine.Limit(time=0.1))
            if "pv" in info_after and len(info_after["pv"]) > 0:
                punishment_move = temp_board.san(info_after["pv"][0])

        punishing_piece = "opponent"
        if punishment_move != "None":
            p_char = punishment_move[0]
            piece_map = {'Q': 'Queen', 'R': 'Rook', 'B': 'Bishop', 'N': 'Knight', 'K': 'King'}
            punishing_piece = piece_map.get(p_char, "Pawn")

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
            if isinstance(current_eval, str) and "M-" in current_eval:  category = "Missing Checkmate"
            elif p_val > 2.5 and eval_delta < -2.0:                      category = "Missed Win"
            elif eval_delta <= -3.0:                                       category = "Blunder"
            elif eval_delta <= -1.2:                                       category = "Mistake"
            elif eval_delta <= -0.6:                                       category = "Inaccuracy"
            elif turn_count <= 10 and eval_delta >= -0.4:                  category = "Opening/Book Move"
        except Exception as math_e:
            print(f"Eval Math Error: {math_e}")

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
    move_number = (len(board.move_stack) // 2) + 1
    temp_board = chess.Board(current_fen) if current_fen else chess.Board()

    if temp_board.is_game_over():
        return jsonify({"status": "error", "message": "The game is already over!"})

    material_status = get_material_score(temp_board)
    tactical_facts  = get_tactical_facts(temp_board)

    try:
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info = engine.analyse(temp_board, chess.engine.Limit(time=1.5))
            best_move_obj = info["pv"][0]
            san_move = temp_board.san(best_move_obj)
            pv_san = []
            test_board = temp_board.copy()
            for m in info["pv"][:4]:
                turn_label = "White" if test_board.turn == chess.WHITE else "Black"
                pv_san.append(f"{turn_label} plays {test_board.san(m)}")
                test_board.push(m)
            expected_line_list = "\n".join([f"- {m}" for m in pv_san])
            game_history = []
            hist_board = chess.Board()
            for move in board.move_stack:
                game_history.append(hist_board.san(move))
                hist_board.push(move)
            moving_piece = temp_board.piece_at(best_move_obj.from_square)
            moving_piece_name = chess.piece_name(moving_piece.piece_type).capitalize() if moving_piece else "Piece"

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
        return jsonify({
            "status": "success",
            "move": san_move,
            "from_sq": best_move_obj.from_square,
            "to_sq": best_move_obj.to_square,
            "explanation": response.choices[0].message.content
        })
    except Exception as e:
        print(f"!!! BEST MOVE ERROR: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to suggest a move."})


@app.route('/sync_position', methods=['POST'])
def sync_position():
    global board
    data = request.json
    fen     = data.get('fen')
    history = data.get('history', [])
    if not fen:
        return jsonify({"status": "error", "message": "No FEN provided"})
    try:
        board = chess.Board()
        for san in history:
            move = board.parse_san(san)
            board.push(move)
        evaluation = get_evaluation(board.fen())
        return jsonify({"status": "success", "evaluation": evaluation})
    except Exception as e:
        try:
            board = chess.Board(fen)
            evaluation = get_evaluation(fen)
            return jsonify({"status": "success", "evaluation": evaluation})
        except Exception as e2:
            return jsonify({"status": "error", "message": str(e2)})


# ─── EVALUATE USER SUGGESTED MOVE ────────────────────────────────────────────

def evaluate_user_suggested_move(board, user_message, history=None):
    import re

    def normalize_move(m):
        if m and m[0] in 'kqrbn':
            return m[0].upper() + m[1:]
        return m

    raw_matches = re.findall(
        r'\b([KQRBNkqrbn]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBNqrbn])?|O-O-O|O-O|0-0-0|0-0)\b',
        user_message
    )

    for raw in raw_matches:
        move_str = normalize_move(raw)
        try:
            move = board.parse_san(move_str)
            if move not in board.legal_moves:
                continue

            eval_before = get_evaluation(board.fen())
            board.push(move)
            eval_after = get_evaluation(board.fen())

            best_reply = "N/A"
            continuation = []
            try:
                with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
                    info = engine.analyse(board, chess.engine.Limit(time=0.4))
                    if "pv" in info and info["pv"]:
                        best_reply = board.san(info["pv"][0])
                        test_b = board.copy()
                        for m in info["pv"][:4]:
                            label = "White" if test_b.turn == chess.WHITE else "Black"
                            continuation.append(f"{label}: {test_b.san(m)}")
                            test_b.push(m)
            except Exception:
                pass

            board.pop()

            def parse_e(e):
                if isinstance(e, str) and "M" in e:
                    return 20.0 if "-" not in e else -20.0
                return float(e)

            delta = parse_e(eval_after) - parse_e(eval_before)

            if delta >= 0.5:      verdict = "STRONG"
            elif delta >= -0.3:   verdict = "REASONABLE"
            elif delta >= -1.0:   verdict = "INACCURACY"
            elif delta >= -2.0:   verdict = "MISTAKE"
            else:                 verdict = "BLUNDER"

            # FIX 2: translate verdict to plain English, no raw numbers passed to AI
            verdict_plain = {
                "STRONG":     "a strong move that improves your position",
                "REASONABLE": "a reasonable move — not the best but not losing",
                "INACCURACY": "an inaccuracy — it slightly weakens your position",
                "MISTAKE":    "a mistake — it gives your opponent a clear advantage",
                "BLUNDER":    "a blunder — it loses significant material or causes serious damage",
            }.get(verdict, verdict)

            tactical = full_move_analysis(board, move)
            tactical_str = format_move_analysis_for_prompt(tactical, move_str)

            return {
                "move": move_str,
                "verdict": verdict,
                "verdict_plain": verdict_plain,
                "best_reply_after": best_reply,
                "continuation": " -> ".join(continuation),
                "tactical_analysis": tactical_str
            }
        except Exception:
            continue
    return None


# ─── ASK COACH ROUTE ─────────────────────────────────────────────────────────

def get_piece_positions(board):
    positions = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p:
            color = "White" if p.color == chess.WHITE else "Black"
            positions.append(
                f"{color} {chess.piece_name(p.piece_type).capitalize()} on {chess.square_name(sq)}"
            )
    return ", ".join(positions) if positions else "No pieces on board."

@app.route('/ask_coach', methods=['POST'])
def ask_coach():
    global board
    data = request.json or {}

    user_question = data.get("question", "").strip()
    fen           = data.get("fen", "")
    pgn           = data.get("pgn", "")
    history       = data.get("history", [])
    current_eval  = data.get("eval", 0)
    player_color  = data.get("player_color", "white")
    game_mode     = data.get("game_mode", "analysis")
    bot_elo       = data.get("bot_elo", None)
    move_number   = data.get("move_number", 1)

    if not user_question:
        return jsonify({"status": "error", "message": "No question received."})

    try:
        temp_board = chess.Board()
        for san in history:
            temp_board.push(temp_board.parse_san(san))
    except Exception:
        try:
            temp_board = chess.Board(fen) if fen else chess.Board()
        except Exception:
            temp_board = chess.Board()

    material          = get_material_score(temp_board)
    tactical_facts    = get_tactical_facts(temp_board)
    game_phase        = get_game_phase(temp_board)
    open_files        = get_open_files(temp_board)
    piece_activity    = get_piece_activity(temp_board)
    white_king_safety = get_king_safety(temp_board, chess.WHITE)
    black_king_safety = get_king_safety(temp_board, chess.BLACK)
    whose_turn        = "White" if temp_board.turn == chess.WHITE else "Black"
    in_check          = "YES — the king is in check." if temp_board.is_check() else "No."

    engine_best = "N/A"
    engine_continuation = []
    try:
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            info = engine.analyse(temp_board, chess.engine.Limit(time=0.5))
            if "pv" in info and info["pv"]:
                engine_best = temp_board.san(info["pv"][0])
                test_b = temp_board.copy()
                for m in info["pv"][:5]:
                    label = "White" if test_b.turn == chess.WHITE else "Black"
                    engine_continuation.append(f"{label}: {test_b.san(m)}")
                    test_b.push(m)
    except Exception:
        pass

    continuation_str = " → ".join(engine_continuation) if engine_continuation else "N/A"

    # FIX 2: no raw eval numbers in suggested_move_str
    suggested_move_analysis = evaluate_user_suggested_move(temp_board, user_question, history)
    suggested_move_str = "NONE — user did not mention a specific move."
    if suggested_move_analysis:
        sm = suggested_move_analysis
        suggested_move_str = (
            f"MOVE MENTIONED: {sm['move']}\n"
            f"Stockfish Verdict: {sm['verdict']} — {sm['verdict_plain']}\n"
            f"Best Opponent Reply After This Move: {sm['best_reply_after']}\n"
            f"Engine Continuation: {sm['continuation']}\n"
            f"--- FULL TACTICAL BREAKDOWN ---\n"
            f"{sm['tactical_analysis']}"
        )

    if isinstance(current_eval, str) and "M" in str(current_eval):
        eval_str = f"Forced mate in {current_eval}"
    else:
        try:
            ev = float(current_eval)
            if ev > 0:    eval_str = f"+{ev:.2f} (White is better)"
            elif ev < 0:  eval_str = f"{ev:.2f} (Black is better)"
            else:         eval_str = "0.00 (Equal position)"
        except Exception:
            eval_str = str(current_eval)

    piece_positions = get_piece_positions(temp_board)
    opponent_str = f"{bot_elo} ELO bot" if bot_elo and game_mode == "play" else "human opponent" if game_mode == "play" else "N/A (Analysis mode)"

    context_block = f"""
=== COMPLETE GAME CONTEXT FOR COACH ===
Game Mode: {game_mode.upper()} - Player is {player_color.capitalize()}{" vs " + opponent_str if game_mode == "play" else " (Analysis Board)"}
Move Number: {move_number} | Whose Turn: {whose_turn} | King In Check: {in_check}

--- POSITION (GROUND TRUTH) ---
FEN: {fen}
CURRENT PIECE LOCATIONS (authoritative — every piece exactly where it is RIGHT NOW):
{piece_positions}
Game Phase: {game_phase}
Stockfish Evaluation: {eval_str}
Engine Best Move HERE: {engine_best}
Engine Continuation: {continuation_str}

--- MATERIAL & TACTICS (ONLY REFERENCE THESE FACTS) ---
Material Balance: {material}
Active Pins: {tactical_facts}
Piece Mobility: {piece_activity}
Open Files: {open_files}
White King Safety: {white_king_safety}
Black King Safety: {black_king_safety}

--- MOVE HISTORY ---
{pgn if pgn else " ".join(history) if history else "No moves yet."}

--- STOCKFISH VERDICT ON USER MENTIONED MOVE ---
{suggested_move_str}
=== END CONTEXT ===
"""

    # FIX 2: Updated laws — no eval numbers, better recapture rule
    coach_system_prompt = (
        f"You are a sharp, direct chess coach. Student is {player_color.capitalize()}"
        f"{' vs a ' + opponent_str if game_mode == 'play' else ' in analysis mode'}. "
        f"Game Phase: {game_phase}.\n\n"
        "YOUR JOB: Answer the student using ONLY the data in the CONTEXT. Be specific. Be a real coach talking to a beginner.\n\n"
        "IRON LAWS:\n"
        "LAW 0 PIECE LOCATIONS: The ONLY source of truth for where pieces are is CURRENT PIECE LOCATIONS. NEVER infer piece location from PGN or move history.\n"
        "LAW 1 GROUND TRUTH: Only mention pieces, squares, and moves in the CONTEXT. Never invent threats or phantom pieces.\n"
        "LAW 2 SUGGESTED MOVE: If CONTEXT has a STOCKFISH VERDICT, your FIRST SENTENCE states plainly if the move is good or bad. Use the verdict_plain text. NEVER say eval numbers, centipawns, or delta. Say 'Qxc8 is a blunder' not 'Qxc8 drops eval by -1.36'.\n"
        "LAW 3 RECAPTURE — MOST IMPORTANT: If TACTICAL BREAKDOWN says RECAPTURE WARNING, explain it like this: 'Your Queen captures the Rook on c8, but Black's Knight on e7 immediately takes back your Queen — so you give up a Queen to win only a Rook, losing material overall.' Be explicit: name WHAT you captured, name WHAT recaptures, name WHICH square, and state the net result clearly.\n"
        "LAW 4 ASSASSIN RULE: For any bad move, name the EXACT opponent piece and move from Engine Continuation that punishes it.\n"
        "LAW 5 TACTICAL MOTIFS: If TACTICAL BREAKDOWN reveals a fork, skewer, discovered attack, or back rank weakness, NAME the motif with exact squares.\n"
        "LAW 6 NO EVAL NUMBERS EVER: Never say eval, centipawns, +1.3, -2.1, delta, or any engine score. Use only plain chess language: loses material, winning advantage, strong move, bad trade.\n"
        "LAW 7 NO GENERIC ADVICE: 'Develop your pieces' and 'control the center' are BANNED unless tied to a specific piece or square from the context.\n"
        "LAW 8 ACKNOWLEDGE THINKING: If student said 'I was thinking X because Y', address their reasoning directly.\n\n"
        "CASE GUIDE:\n"
        "BLUNDER: State it is a blunder in plain English. Name what is lost and which opponent piece wins it.\n"
        "MISTAKE: State it is a mistake. Explain the specific concession with exact pieces and squares.\n"
        "INACCURACY: State it is an inaccuracy. Explain the tempo loss or slight concession in plain terms.\n"
        "REASONABLE or STRONG: Confirm it and explain WHY using specific pieces and squares from the data.\n"
        "RECAPTURE: Spell out the full exchange — what you capture, what takes back, which square, net result in plain English.\n"
        "FORK detected: Name it: Your Knight on X forks the King on Y and the Rook on Z.\n"
        "DISCOVERED ATTACK: Moving the Bishop reveals your Rook attacking the opponent's Queen on X.\n"
        "SKEWER detected: Your Rook skewers the King on e8, winning the Queen on e1 behind it.\n"
        "BACK RANK WEAKNESS: Warn: Your back rank is vulnerable to checkmate from the Rook on X.\n"
        "Student asks for a plan: Use engine best move and continuation. Explain in 2-3 moves with exact pieces and squares.\n"
        "Student vents: One sentence acknowledgment then one concrete tip from the current position.\n\n"
        "FORMAT: MAX 4 sentences. Coach voice, direct, not academic. No bullet points. No numbered lists. "
        "Never start with 'Great question', 'Certainly', 'Of course', or any filler. First word must be about chess."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": coach_system_prompt},
                {"role": "user",   "content": f"CONTEXT:\n{context_block}\n\nSTUDENT'S MESSAGE:\n{user_question}"}
            ],
            temperature=0.4,
            max_tokens=300
        )
        answer = response.choices[0].message.content
        return jsonify({"status": "success", "answer": answer})
    except Exception as e:
        print(f"!!! ASK COACH ERROR: {e}")
        return jsonify({"status": "error", "message": "Coach is unavailable right now."})


if __name__ == '__main__':
    app.run(debug=True)