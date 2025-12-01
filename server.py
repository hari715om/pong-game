import asyncio
import json
import math
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

# --- GAME SETTINGS ---
WIDTH, HEIGHT = 800, 600
PADDLE_WIDTH, PADDLE_HEIGHT = 15, 100
BALL_SIZE = 15
PADDLE_SPEED = 8
BALL_SPEED = 6
FPS = 60

# --- GAME STATE MANAGER ---
class PongGame:
    def __init__(self):
        self.connections: List[WebSocket] = [] # Stores active player sockets
        # Paddle Y positions (0 = Top)
        self.p1_y = HEIGHT // 2 - PADDLE_HEIGHT // 2
        self.p2_y = HEIGHT // 2 - PADDLE_HEIGHT // 2
        # Ball State
        self.ball_x = WIDTH // 2
        self.ball_y = HEIGHT // 2
        self.ball_dx = BALL_SPEED
        self.ball_dy = BALL_SPEED
        # Scores
        self.score_p1 = 0
        self.score_p2 = 0
        
        # Input State (What keys are currently pressed?)
        self.p1_move = 0 # -1 (up), 0 (stop), 1 (down)
        self.p2_move = 0 

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)
        
        # Assign Player Number based on order of joining
        if len(self.connections) == 1:
            await websocket.send_json({"type": "init", "player_no": 1})
        elif len(self.connections) == 2:
            await websocket.send_json({"type": "init", "player_no": 2})
        else:
            await websocket.send_json({"type": "full"})
            await websocket.close()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)
            # Reset game if someone leaves
            self.score_p1 = 0
            self.score_p2 = 0
            self.reset_ball()

    def reset_ball(self):
        self.ball_x = WIDTH // 2
        self.ball_y = HEIGHT // 2
        self.ball_dx = -self.ball_dx # Serve to other player

    async def game_loop(self):
        """ The Physics Engine running at 60 FPS """
        while True:
            if len(self.connections) < 2:
                # Pause if not enough players
                await asyncio.sleep(1/FPS)
                continue

            # 1. Update Paddles
            self.p1_y += self.p1_move * PADDLE_SPEED
            self.p2_y += self.p2_move * PADDLE_SPEED

            # Clamp Paddles (Don't let them go off screen)
            self.p1_y = max(0, min(HEIGHT - PADDLE_HEIGHT, self.p1_y))
            self.p2_y = max(0, min(HEIGHT - PADDLE_HEIGHT, self.p2_y))

            # 2. Update Ball
            self.ball_x += self.ball_dx
            self.ball_y += self.ball_dy

            # 3. Collisions
            # Top/Bottom Walls
            if self.ball_y <= 0 or self.ball_y + BALL_SIZE >= HEIGHT:
                self.ball_dy *= -1

            # Paddles (Simple AABB Collision)
            # Player 1 (Left)
            p1_rect = (0, self.p1_y, PADDLE_WIDTH, PADDLE_HEIGHT) # x, y, w, h
            if (self.ball_x <= PADDLE_WIDTH and 
                self.p1_y < self.ball_y + BALL_SIZE and 
                self.p1_y + PADDLE_HEIGHT > self.ball_y):
                self.ball_dx = abs(self.ball_dx) # Force moves Right

            # Player 2 (Right)
            if (self.ball_x + BALL_SIZE >= WIDTH - PADDLE_WIDTH and 
                self.p2_y < self.ball_y + BALL_SIZE and 
                self.p2_y + PADDLE_HEIGHT > self.ball_y):
                self.ball_dx = -abs(self.ball_dx) # Force moves Left

            # 4. Scoring
            if self.ball_x < 0:
                self.score_p2 += 1
                self.reset_ball()
            elif self.ball_x > WIDTH:
                self.score_p1 += 1
                self.reset_ball()

            # 5. Broadcast State
            game_state = {
                "type": "update",
                "p1_y": self.p1_y,
                "p2_y": self.p2_y,
                "ball_x": self.ball_x,
                "ball_y": self.ball_y,
                "score_p1": self.score_p1,
                "score_p2": self.score_p2
            }
            
            # Send to all connected players
            for conn in self.connections:
                try:
                    await conn.send_json(game_state)
                except:
                    pass # Handle connection drops elsewhere

            await asyncio.sleep(1/FPS)

game = PongGame()

# Start the game loop in the background when app starts
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(game.game_loop())

@app.get("/")
async def get():
    # Serve the HTML file directly
    with open("index.html", "r") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await game.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Handle Inputs
            if data['type'] == 'input':
                player_no = data['player']
                direction = data['direction'] # 1, -1, or 0
                
                if player_no == 1:
                    game.p1_move = direction
                elif player_no == 2:
                    game.p2_move = direction
    except WebSocketDisconnect:
        game.disconnect(websocket)