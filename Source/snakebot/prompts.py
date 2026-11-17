"""The words we send to the AI: the rules of the game and what each move means.

This module imports nothing else from the bot."""


# These are the rules we tell the AI with every board.
JEV_INSTRUCTIONS = (
    "This grid shows a game of snake, {cols} columns across by {rows} rows down. "
    "Reading the grid: H marks the head, N the neck directly behind it, B the rest of the body, "
    "T the last segment, F the food, and a dot a free square. "
    "On every step the head advances one square in the chosen direction and the other segments trail behind it. "
    "Steering off the grid or onto the body ends the game. "
    "Reversing is impossible: a command pointing back at N does nothing and the snake continues ahead. "
    "Swallowing the food adds one square of length. "
    "Pick the next direction: survive, avoid dead-end pockets where the tail is unreachable, and reach the food."
)

JEV_DESCRIPTIONS = {
    "Up": "Head goes one square up, to the row above.",
    "Down": "Head goes one square down, to the row below.",
    "Left": "Head goes one square left, to the column on its left.",
    "Right": "Head goes one square right, to the column on its right.",
}
