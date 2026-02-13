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



if __name__ == '__main__':

    app.run(debug=True)